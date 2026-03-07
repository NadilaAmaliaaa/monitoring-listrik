import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import func
from database import get_session
from models.data import Sensor, SensorReading
from models.building import Building
from config import Config

# ── Alarm hook (import di sini agar tidak circular import) ───────────────────
try:
    from mqtt.alarm_hook import run_alarm_check
    ALARM_CHECK_AVAILABLE = True
    logger_temp = logging.getLogger(__name__)
    logger_temp.info("✓ Alarm hook loaded — threshold checking ENABLED")
except ImportError:
    ALARM_CHECK_AVAILABLE = False
    logger_temp = logging.getLogger(__name__)
    logger_temp.warning("⚠ Alarm hook not found — threshold checking DISABLED")

# -------------------- CONFIGURATIONS FROM ENV --------------------
MAX_BUCKETS_PER_SENSOR = Config.MAX_BUCKETS_PER_SENSOR
FLUSH_INTERVAL_SEC = Config.FLUSH_INTERVAL_SEC
CLEANUP_INTERVAL_MIN = Config.CLEANUP_INTERVAL_MIN
BUCKET_CUTOFF_SEC = Config.BUCKET_CUTOFF_SEC
OLD_BUCKET_THRESHOLD_HOURS = Config.OLD_BUCKET_THRESHOLD_HOURS

TARIF_PER_KWH = Config.TARIF_PER_KWH
PPJ = Config.PPJ

# -------------------- LOGGING SETUP --------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('mqtt_handler.log')
    ]
)
logger = logging.getLogger(__name__)


# -------------------- THREAD SAFETY --------------------
agg_lock = threading.Lock()
db_write_lock = threading.Lock()

# -------------------- AGGREGATION BUFFER --------------------
agg_buffer = {}


class SensorDataHandler:
    """Handler untuk menyimpan dan agregasi data sensor"""
    
    @staticmethod
    def get_sensor_id_from_topic(topic: str) -> int:
        try:
            parts = topic.split("/")
            if len(parts) != 3 or parts[0] != "sensor":
                logger.warning(f"Invalid topic format: {topic}")
                return None
            
            building_code = parts[1]
            sensor_name = parts[2]
            
            session = get_session()
            try:
                result = (
                    session.query(Sensor.id)
                    .join(Building, Sensor.building_id == Building.id)
                    .filter(Building.code == building_code)
                    .filter(Sensor.name == sensor_name)
                    .first()
                )
                
                if result:
                    logger.debug(f"Found sensor_id {result[0]} for topic {topic}")
                    return result[0]
                else:
                    logger.warning(f"No sensor found for topic: {topic}")
                    return None
                    
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Error getting sensor_id from topic {topic}: {e}")
            return None
    
    @staticmethod
    def calculate_energy_cost(power_watt: float, duration_sec: float = 5.0) -> tuple:
        try:
            energi_wh = power_watt * (duration_sec / 3600.0)
            energi_kwh = energi_wh / 1000.0
            biaya = energi_kwh * TARIF_PER_KWH * (1 + PPJ)
            return energi_kwh, biaya
        except Exception as e:
            logger.error(f"Error calculating energy/cost: {e}")
            return 0.0, 0.0
    
    @staticmethod
    def save_sensor_reading(sensor_id: int, data: dict, max_retries: int = 3):
        """
        Menyimpan data sensor ke database dengan retry mechanism.
        Alarm check TIDAK dijalankan di sini — hanya dipanggil dari
        flush_matured_buckets() saat data sudah final (nilai rata-rata
        bucket penuh, bukan intermediate update).
        """
        required_keys = ['voltage', 'current', 'power', 'energy', 
                        'frequency', 'power_factor', 'peak_voltage', 'peak_current']
        
        if not all(k in data for k in required_keys):
            logger.warning(f"Incomplete data for sensor {sensor_id}: {list(data.keys())}")
            return False
        
        timestamp = data.get('force_timestamp', datetime.utcnow())
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        
        for attempt in range(max_retries):
            with db_write_lock:
                session = get_session()
                try:
                    existing = (
                        session.query(SensorReading)
                        .filter(
                            SensorReading.sensor_id == sensor_id,
                            SensorReading.timestamp == timestamp
                        )
                        .first()
                    )
                    
                    if existing:
                        existing.voltage      = float(data['voltage'])
                        existing.current      = float(data['current'])
                        existing.power        = float(data['power'])
                        existing.energy       = float(data['energy'])
                        existing.frequency    = float(data['frequency'])
                        existing.power_factor = float(data['power_factor'])
                        existing.peak_voltage = float(data['peak_voltage'])
                        existing.peak_current = float(data['peak_current'])
                        saved_reading = existing
                        logger.debug(f"Updated existing reading for sensor {sensor_id}")
                    else:
                        saved_reading = SensorReading(
                            sensor_id=sensor_id,
                            timestamp=timestamp,
                            voltage=float(data['voltage']),
                            current=float(data['current']),
                            power=float(data['power']),
                            energy=float(data['energy']),
                            frequency=float(data['frequency']),
                            power_factor=float(data['power_factor']),
                            peak_voltage=float(data['peak_voltage']),
                            peak_current=float(data['peak_current'])
                        )
                        session.add(saved_reading)
                    
                    session.commit()
                    logger.info(
                        f"✓ Data saved for sensor {sensor_id} "
                        f"@ {timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
                    )

                    # Return plain dict — aman dipakai setelah session.close()
                    # SQLAlchemy object akan expired/detached setelah session ditutup
                    return {
                        'sensor_id':    sensor_id,
                        'timestamp':    timestamp,
                        'voltage':      float(data['voltage']),
                        'current':      float(data['current']),
                        'power':        float(data['power']),
                        'energy':       float(data['energy']),
                        'frequency':    float(data['frequency']),
                        'power_factor': float(data['power_factor']),
                        'peak_voltage': float(data['peak_voltage']),
                        'peak_current': float(data['peak_current']),
                    }
                    
                except Exception as e:
                    session.rollback()
                    logger.warning(
                        f"Save attempt {attempt+1}/{max_retries} failed "
                        f"for sensor {sensor_id}: {e}"
                    )
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                    
                finally:
                    session.close()
        
        logger.error(
            f"✗ Failed to save data for sensor {sensor_id} "
            f"after {max_retries} retries"
        )
        return False


class AggregationBuffer:
    """Buffer untuk agregasi data sensor dengan bucketing per menit"""
    
    @staticmethod
    def accumulate_data(sensor_id: int, data: dict):
        """Akumulasi data sensor ke dalam bucket waktu"""
        now = datetime.utcnow().replace(tzinfo=timezone.utc)
        bucket_time = now.replace(second=0, microsecond=0)
        bucket_ts = bucket_time.timestamp()
        
        with agg_lock:
            if sensor_id not in agg_buffer:
                agg_buffer[sensor_id] = {}
            
            if len(agg_buffer[sensor_id]) >= MAX_BUCKETS_PER_SENSOR:
                oldest_key = min(agg_buffer[sensor_id].keys())
                del agg_buffer[sensor_id][oldest_key]
                logger.warning(
                    f"Bucket limit reached for sensor {sensor_id}, removed oldest bucket"
                )
            
            if bucket_ts not in agg_buffer[sensor_id]:
                agg_buffer[sensor_id][bucket_ts] = {
                    "sums": {
                        'voltage': 0.0, 'current': 0.0, 'power': 0.0,
                        'energy': 0.0, 'frequency': 0.0, 'power_factor': 0.0
                    },
                    "count": 0,
                    "timestamp_obj": bucket_time,
                    "peak_voltage": float('-inf'),
                    "peak_current": float('-inf')
                }
            
            buf = agg_buffer[sensor_id][bucket_ts]
            
            try:
                power = float(data.get('daya', 0.0))
                energy_kwh, cost = SensorDataHandler.calculate_energy_cost(power)
                
                buf['sums']['voltage']      += float(data.get('tegangan', 0.0))
                buf['sums']['current']      += float(data.get('arus', 0.0))
                buf['sums']['power']        += power
                buf['sums']['energy']       += energy_kwh
                buf['sums']['frequency']    += float(data.get('frekuensi', 0.0))
                buf['sums']['power_factor'] += float(data.get('pf', 0.0))
                buf['count'] += 1
                
                voltage = float(data.get('tegangan', 0.0))
                current = float(data.get('arus', 0.0))
                buf['peak_voltage'] = max(buf['peak_voltage'], voltage)
                buf['peak_current'] = max(buf['peak_current'], current)
                
                logger.debug(
                    f"Accumulated for sensor {sensor_id}, "
                    f"bucket {bucket_time.strftime('%H:%M')}, "
                    f"count: {buf['count']}"
                )
                
            except Exception as e:
                logger.error(f"Error accumulating data for sensor {sensor_id}: {e}")
    
    @staticmethod
    def flush_matured_buckets(sensor_id: int):
        """
        Flush bucket yang sudah matang.

        Bucket dianggap matang jika:
          1. Sudah melewati BUCKET_CUTOFF_SEC sejak awal bucket, DAN
          2. Bucket timestamp + 60 detik < sekarang
             (menjamin menit bucket sudah benar-benar berlalu)

        Ini mencegah alarm check terjadi sebelum data final.
        """
        now_ts = time.time()
        cutoff_time = now_ts - BUCKET_CUTOFF_SEC

        with agg_lock:
            if sensor_id not in agg_buffer:
                return

            bucket_keys = list(agg_buffer[sensor_id].keys())

            for b_key in bucket_keys:
                # Kondisi 1: belum melewati BUCKET_CUTOFF_SEC
                if b_key > cutoff_time:
                    continue

                # Kondisi 2: menit bucket belum selesai
                # b_key adalah timestamp awal menit (detik=0),
                # jadi b_key + 60 = awal menit berikutnya
                if b_key + 60 > now_ts:
                    logger.debug(
                        f"Bucket {datetime.fromtimestamp(b_key).strftime('%H:%M')} "
                        f"sensor {sensor_id} belum matang — menit belum selesai, skip"
                    )
                    continue
                
                buf   = agg_buffer[sensor_id][b_key]
                count = buf['count']
                
                if count > 0:
                    sums = buf['sums']
                    averaged_data = {
                        "voltage":         sums['voltage'] / count,
                        "current":         sums['current'] / count,
                        "power":           sums['power'],
                        "energy":          sums['energy'],
                        "frequency":       sums['frequency'] / count,
                        "power_factor":    sums['power_factor'] / count,
                        "force_timestamp": buf['timestamp_obj'],
                        "peak_voltage":    buf['peak_voltage'],
                        "peak_current":    buf['peak_current']
                    }
                    
                    try:
                        # Data sudah final (bucket matang) — jalankan alarm check
                        saved = SensorDataHandler.save_sensor_reading(sensor_id, averaged_data)
                        logger.info(
                            f"Flushed bucket for sensor {sensor_id}, "
                            f"time: {buf['timestamp_obj'].strftime('%H:%M')}, "
                            f"samples: {count}"
                        )
                        # ── ALARM CHECK — hanya di sini, setelah data final ──
                        if saved and ALARM_CHECK_AVAILABLE:
                            try:
                                alarm_session = get_session()
                                run_alarm_check(alarm_session, sensor_id, saved)
                                alarm_session.close()
                            except Exception as alarm_err:
                                logger.error(
                                    f"Alarm check failed for sensor {sensor_id}: {alarm_err}",
                                    exc_info=True
                                )
                        # ─────────────────────────────────────────────────────
                    except Exception as e:
                        logger.error(
                            f"Error flushing bucket for sensor {sensor_id}: {e}"
                        )
                
                del agg_buffer[sensor_id][b_key]
    
    @staticmethod
    def cleanup_old_buckets():
        """Hapus bucket yang terlalu lama untuk menghemat memori"""
        cutoff_ts = time.time() - (OLD_BUCKET_THRESHOLD_HOURS * 3600)
        
        with agg_lock:
            for sensor_id in list(agg_buffer.keys()):
                old_keys = [k for k in agg_buffer[sensor_id] if k < cutoff_ts]
                
                for k in old_keys:
                    del agg_buffer[sensor_id][k]
                    logger.info(
                        f"Cleaned old bucket for sensor {sensor_id} "
                        f"@ {datetime.fromtimestamp(k).strftime('%Y-%m-%d %H:%M')}"
                    )
                
                if not agg_buffer[sensor_id]:
                    del agg_buffer[sensor_id]
    
    @staticmethod
    def start_flush_worker():
        """Jalankan background scheduler untuk flush dan cleanup"""
        scheduler = BackgroundScheduler()
        
        scheduler.add_job(
            func=lambda: [
                AggregationBuffer.flush_matured_buckets(sid)
                for sid in list(agg_buffer.keys())
            ],
            trigger=IntervalTrigger(seconds=FLUSH_INTERVAL_SEC),
            id='flush_job',
            name='Flush matured buckets'
        )
        
        scheduler.add_job(
            func=AggregationBuffer.cleanup_old_buckets,
            trigger=IntervalTrigger(minutes=CLEANUP_INTERVAL_MIN),
            id='cleanup_job',
            name='Cleanup old buckets'
        )
        
        scheduler.start()
        logger.info(f"✓ Flush worker started (interval: {FLUSH_INTERVAL_SEC}s)")
        logger.info(f"✓ Cleanup worker started (interval: {CLEANUP_INTERVAL_MIN}min)")
        
        return scheduler


# -------------------- HELPER FUNCTIONS --------------------

def handle_mqtt_sensor_message(topic: str, payload: dict):
    """Handler untuk pesan MQTT dari sensor — hanya akumulasi ke buffer."""
    try:
        sensor_id = SensorDataHandler.get_sensor_id_from_topic(topic)
        
        if not sensor_id:
            logger.warning(f"Cannot process message from unknown topic: {topic}")
            return
        
        # Akumulasi ke buffer — alarm check terjadi saat flush (1 menit)
        AggregationBuffer.accumulate_data(sensor_id, payload)
        
    except Exception as e:
        logger.error(f"Error handling MQTT message from {topic}: {e}")


def get_buildings_with_sensors():
    """Mendapatkan daftar building beserta sensor-sensornya"""
    session = get_session()
    try:
        results = (
            session.query(
                Building.id.label('building_id'),
                Building.name.label('building_name'),
                Building.code.label('building_code'),
                Sensor.id.label('sensor_id'),
                Sensor.name.label('sensor_name')
            )
            .outerjoin(Sensor, Building.id == Sensor.building_id)
            .order_by(Building.id)
            .all()
        )
        
        buildings = {}
        
        for row in results:
            building_name = row.building_name
            
            if building_name not in buildings:
                buildings[building_name] = {
                    'building_id': row.building_id,
                    'building_code': row.building_code,
                    'sensors': []
                }
            
            if row.sensor_id:
                buildings[building_name]['sensors'].append({
                    'sensor_id': row.sensor_id,
                    'sensor_name': row.sensor_name,
                    'topic': f"sensor/{row.building_code}/{row.sensor_name}"
                })
        
        logger.info(f"Retrieved {len(buildings)} buildings with sensors")
        return buildings
        
    except Exception as e:
        logger.error(f"Error getting buildings with sensors: {e}")
        return {}
        
    finally:
        session.close()