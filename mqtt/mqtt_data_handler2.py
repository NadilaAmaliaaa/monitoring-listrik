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
FLUSH_INTERVAL_SEC     = Config.FLUSH_INTERVAL_SEC
CLEANUP_INTERVAL_MIN   = Config.CLEANUP_INTERVAL_MIN
BUCKET_CUTOFF_SEC      = Config.BUCKET_CUTOFF_SEC
OLD_BUCKET_THRESHOLD_HOURS = Config.OLD_BUCKET_THRESHOLD_HOURS

TARIF_PER_KWH = Config.TARIF_PER_KWH
PPJ           = Config.PPJ

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
# Dua lock TIDAK boleh dipegang secara bersamaan (cegah deadlock).
# Aturan:
#   agg_lock   → hanya untuk operasi baca/tulis agg_buffer (cepat, in-memory)
#   db_write_lock → hanya untuk operasi tulis ke database
# flush_matured_buckets() mengambil data dari buffer di bawah agg_lock,
# lalu melepas agg_lock sebelum menyentuh db_write_lock.
agg_lock      = threading.Lock()
db_write_lock = threading.Lock()

# -------------------- AGGREGATION BUFFER --------------------
# Struktur bucket  : { sensor_id: { bucket_ts_float: { ... } } }
# Struktur last_ts : { sensor_id: float }  ← UNIX timestamp sampel terakhir
#                    Disimpan TERPISAH dari bucket agar carry-over antar menit.
agg_buffer       = {}
sensor_last_ts   = {}   # { sensor_id: float }


class SensorDataHandler:
    """Handler untuk menyimpan dan agregasi data sensor"""

    @staticmethod
    def get_sensor_id_from_topic(topic: str):
        try:
            parts = topic.split("/")
            if len(parts) != 3 or parts[0] != "sensor":
                logger.warning(f"Invalid topic format: {topic}")
                return None

            building_code = parts[1]
            sensor_name   = parts[2]

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
    def calculate_energy_cost(power_watt: float, duration_sec: float) -> tuple:
        """
        Hitung energi (kWh) dan biaya dari satu sampel daya.

        Args:
            power_watt  : daya sesaat dalam Watt
            duration_sec: durasi aktual sampel dalam detik
                          (dihitung dari selisih timestamp antar sampel,
                           bukan hardcoded 5 detik)

        Returns:
            (energi_kwh, biaya_rupiah)
        """
        try:
            energi_wh  = power_watt * (duration_sec / 3600.0)
            energi_kwh = energi_wh / 1000.0
            biaya      = energi_kwh * TARIF_PER_KWH * (1 + PPJ)
            return energi_kwh, biaya
        except Exception as e:
            logger.error(f"Error calculating energy/cost: {e}")
            return 0.0, 0.0

    @staticmethod
    def save_sensor_reading(sensor_id: int, data: dict, max_retries: int = 3):
        """
        Simpan data sensor ke database dengan retry mechanism.

        Mengembalikan dict plain (aman dipakai setelah session tutup),
        atau False jika semua retry gagal.

        Alarm check TIDAK dijalankan di sini — hanya dari
        flush_matured_buckets() setelah data bucket benar-benar final.
        """
        required_keys = [
            'voltage', 'current', 'power', 'energy',
            'frequency', 'power_factor', 'peak_voltage', 'peak_current'
        ]

        if not all(k in data for k in required_keys):
            logger.warning(
                f"Incomplete data for sensor {sensor_id}: {list(data.keys())}"
            )
            return False

        timestamp = data.get('force_timestamp', datetime.utcnow())
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        for attempt in range(max_retries):
            with db_write_lock:          # ← db_write_lock saja, TIDAK agg_lock
                session = get_session()
                try:
                    existing = (
                        session.query(SensorReading)
                        .filter(
                            SensorReading.sensor_id == sensor_id,
                            SensorReading.timestamp  == timestamp
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
                        existing.cost         = float(data.get('cost', 0.0))
                        logger.debug(
                            f"Updated existing reading for sensor {sensor_id}"
                        )
                    else:
                        session.add(SensorReading(
                            sensor_id    = sensor_id,
                            timestamp    = timestamp,
                            voltage      = float(data['voltage']),
                            current      = float(data['current']),
                            power        = float(data['power']),
                            energy       = float(data['energy']),
                            frequency    = float(data['frequency']),
                            power_factor = float(data['power_factor']),
                            peak_voltage = float(data['peak_voltage']),
                            peak_current = float(data['peak_current']),
                            cost         = float(data.get('cost', 0.0))
                        ))

                    session.commit()
                    logger.info(
                        f"✓ Data saved for sensor {sensor_id} "
                        f"@ {timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
                    )

                    # Kembalikan plain dict — aman setelah session.close()
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
                        'cost':         float(data.get('cost', 0.0)),
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
    """Buffer agregasi data sensor dengan bucketing per menit"""

    # ------------------------------------------------------------------ #
    #  Struktur satu bucket:
    #  {
    #    "sums": { voltage, current, power, energy, frequency,
    #              power_factor, cost },   ← energy & cost di-SUM
    #    "count": int,                     ← jumlah sampel (untuk avg power dll)
    #    "timestamp_obj": datetime,        ← awal menit (UTC, aware)
    #    "peak_voltage": float,
    #    "peak_current": float,
    #  }
    #
    #  Durasi antar sampel dihitung dari sensor_last_ts[sensor_id] yang
    #  hidup di level sensor (bukan bucket), sehingga carry-over terjadi
    #  otomatis saat menit berganti dan bucket baru dibuat.
    # ------------------------------------------------------------------ #

    @staticmethod
    def _flush_bucket_to_db(sensor_id: int, buf: dict):
        """
        Hitung rata-rata dari buffer bucket dan simpan ke DB.
        Dipanggil di luar agg_lock.

        Returns:
            dict hasil simpan, atau False jika gagal.
        """
        count = buf['count']
        if count == 0:
            return False

        sums = buf['sums']
        averaged_data = {
            "voltage":         sums['voltage']      / count,
            "current":         sums['current']      / count,
            "power":           sums['power']        / count,   # rata-rata daya
            "energy":          sums['energy'],                 # total energi (kWh)
            "cost":            sums['cost'],                   # total biaya
            "frequency":       sums['frequency']    / count,
            "power_factor":    sums['power_factor'] / count,
            "force_timestamp": buf['timestamp_obj'],
            "peak_voltage":    buf['peak_voltage'],
            "peak_current":    buf['peak_current'],
        }

        saved = SensorDataHandler.save_sensor_reading(sensor_id, averaged_data)

        if saved:
            logger.info(
                f"Flushed bucket sensor {sensor_id} "
                f"@ {buf['timestamp_obj'].strftime('%H:%M')}, "
                f"samples: {count}, "
                f"energy: {sums['energy']:.6f} kWh, "
                f"cost: {sums['cost']:.4f}"
            )

            # Alarm check — hanya setelah data final (bucket matang)
            if ALARM_CHECK_AVAILABLE:
                try:
                    alarm_session = get_session()
                    run_alarm_check(alarm_session, sensor_id, saved)
                    alarm_session.close()
                except Exception as alarm_err:
                    logger.error(
                        f"Alarm check failed for sensor {sensor_id}: {alarm_err}",
                        exc_info=True
                    )

        return saved

    @staticmethod
    def accumulate_data(sensor_id: int, data: dict):
        """
        Akumulasi satu sampel MQTT ke bucket menit yang sesuai.

        Energy dan cost dihitung berdasarkan durasi aktual antar sampel
        (bukan hardcoded 5 detik) sehingga tetap akurat saat ada
        packet-loss, reconnect, atau jitter.
        """
        now         = datetime.utcnow().replace(tzinfo=timezone.utc)
        now_ts      = now.timestamp()
        bucket_time = now.replace(second=0, microsecond=0)
        bucket_ts   = bucket_time.timestamp()

        with agg_lock:
            if sensor_id not in agg_buffer:
                agg_buffer[sensor_id] = {}

            # Eviction: jika bucket sudah penuh, flush dulu bucket terlama
            # sebelum menghapusnya agar data tidak hilang.
            if len(agg_buffer[sensor_id]) >= MAX_BUCKETS_PER_SENSOR:
                oldest_key = min(agg_buffer[sensor_id].keys())
                oldest_buf = agg_buffer[sensor_id].pop(oldest_key)
                logger.warning(
                    f"Bucket limit reached for sensor {sensor_id}, "
                    f"force-flushing oldest bucket "
                    f"@ {datetime.fromtimestamp(oldest_key).strftime('%H:%M')}"
                )
                # Flush di luar lock (lihat catatan di bawah) —
                # di sini kita copy dulu lalu flush setelah keluar lock.
                # Namun karena kita sudah pop, simpan sementara untuk flush
                # setelah blok with selesai.
                evicted_buf = oldest_buf
            else:
                evicted_buf = None

            # Buat bucket baru jika belum ada
            if bucket_ts not in agg_buffer[sensor_id]:
                agg_buffer[sensor_id][bucket_ts] = {
                    "sums": {
                        'voltage': 0.0, 'current': 0.0, 'power': 0.0,
                        'energy': 0.0, 'frequency': 0.0,
                        'power_factor': 0.0, 'cost': 0.0
                    },
                    "count":         0,
                    "timestamp_obj": bucket_time,
                    "peak_voltage":  float('-inf'),
                    "peak_current":  float('-inf'),
                    # last_sample_ts TIDAK disimpan di bucket —
                    # carry-over antar menit ditangani sensor_last_ts di bawah
                }

            buf = agg_buffer[sensor_id][bucket_ts]

            # --- Hitung durasi aktual antar sampel (level sensor, bukan bucket) ---
            # sensor_last_ts[sensor_id] bertahan lintas bucket/menit sehingga
            # sampel pertama di menit baru tetap mendapat durasi yang akurat.
            last_ts = sensor_last_ts.get(sensor_id)
            if last_ts is None:
                # Benar-benar sampel pertama sejak server start untuk sensor ini
                duration_sec = 5.0
                logger.info(
                    f"Sensor {sensor_id}: sampel pertama sejak start, "
                    f"pakai durasi nominal 5.0s"
                )
            else:
                duration_sec = now_ts - last_ts
                # Clamp: jangan lebih dari 2 menit (reconnect / outage)
                duration_sec = min(duration_sec, 120.0)
                # Jangan kurang dari 0.1 detik (clock glitch)
                duration_sec = max(duration_sec, 0.1)

            # Update timestamp terakhir di level sensor (carry-over lintas bucket)
            sensor_last_ts[sensor_id] = now_ts
            # -----------------------------------------------------------------------

            try:
                power      = float(data.get('daya', 0.0))
                voltage    = float(data.get('tegangan', 0.0))
                current    = float(data.get('arus', 0.0))
                frequency  = float(data.get('frekuensi', 0.0))
                pf         = float(data.get('pf', 0.0))

                # Energy dihitung dari daya × durasi aktual sampel ini
                energy_kwh, cost = SensorDataHandler.calculate_energy_cost(
                    power, duration_sec
                )

                buf['sums']['voltage']      += voltage
                buf['sums']['current']      += current
                buf['sums']['power']        += power
                buf['sums']['energy']       += energy_kwh   # SUM ← benar
                buf['sums']['cost']         += cost          # SUM ← benar
                buf['sums']['frequency']    += frequency
                buf['sums']['power_factor'] += pf
                buf['count']                += 1

                buf['peak_voltage'] = max(buf['peak_voltage'], voltage)
                buf['peak_current'] = max(buf['peak_current'], current)

                logger.debug(
                    f"Accumulated sensor {sensor_id} "
                    f"bucket {bucket_time.strftime('%H:%M')}, "
                    f"count: {buf['count']}, "
                    f"duration: {duration_sec:.1f}s, "
                    f"energy_sample: {energy_kwh:.7f} kWh"
                )

            except Exception as e:
                logger.error(
                    f"Error accumulating data for sensor {sensor_id}: {e}"
                )

        # Flush evicted bucket DI LUAR agg_lock untuk hindari deadlock
        if evicted_buf is not None:
            AggregationBuffer._flush_bucket_to_db(sensor_id, evicted_buf)

    @staticmethod
    def flush_matured_buckets(sensor_id: int):
        """
        Flush bucket yang sudah matang ke database.

        Bucket dianggap matang jika:
          1. bucket_ts <= now - BUCKET_CUTOFF_SEC  (sudah melewati cutoff), DAN
          2. bucket_ts + 60 <= now                 (menit bucket sudah berlalu)

        PENTING — dua-fase untuk hindari deadlock:
          Fase 1: ambil semua bucket matang dari buffer (di bawah agg_lock, cepat).
          Fase 2: flush ke DB & jalankan alarm check (di LUAR agg_lock).
        """
        now_ts      = time.time()
        cutoff_time = now_ts - BUCKET_CUTOFF_SEC

        # ── Fase 1: kumpulkan bucket matang (di bawah agg_lock) ──────────
        matured = []   # list of (b_key, buf_dict)

        with agg_lock:
            if sensor_id not in agg_buffer:
                return

            for b_key in list(agg_buffer[sensor_id].keys()):
                # Kondisi 1: belum melewati cutoff
                if b_key > cutoff_time:
                    continue

                # Kondisi 2: menit bucket belum selesai
                if b_key + 60 > now_ts:
                    logger.debug(
                        f"Bucket {datetime.fromtimestamp(b_key).strftime('%H:%M')} "
                        f"sensor {sensor_id} belum matang — menit belum selesai, skip"
                    )
                    continue

                # Matang → ambil dan hapus dari buffer
                matured.append((b_key, agg_buffer[sensor_id].pop(b_key)))

        # ── Fase 2: flush ke DB di luar agg_lock ─────────────────────────
        for b_key, buf in matured:
            try:
                AggregationBuffer._flush_bucket_to_db(sensor_id, buf)
            except Exception as e:
                logger.error(
                    f"Error flushing bucket sensor {sensor_id} "
                    f"@ {datetime.fromtimestamp(b_key).strftime('%H:%M')}: {e}"
                )

    @staticmethod
    def cleanup_old_buckets():
        """Hapus bucket yang terlalu lama (melebihi OLD_BUCKET_THRESHOLD_HOURS)."""
        cutoff_ts = time.time() - (OLD_BUCKET_THRESHOLD_HOURS * 3600)

        with agg_lock:
            for sensor_id in list(agg_buffer.keys()):
                old_keys = [k for k in agg_buffer[sensor_id] if k < cutoff_ts]

                for k in old_keys:
                    del agg_buffer[sensor_id][k]
                    logger.info(
                        f"Cleaned old bucket sensor {sensor_id} "
                        f"@ {datetime.fromtimestamp(k).strftime('%Y-%m-%d %H:%M')}"
                    )

                if not agg_buffer[sensor_id]:
                    del agg_buffer[sensor_id]

    @staticmethod
    def start_flush_worker():
        """Jalankan background scheduler untuk flush dan cleanup."""
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
    """
    Handler untuk pesan MQTT dari sensor.
    Hanya mengakumulasi data ke buffer; alarm check terjadi saat flush.
    """
    try:
        sensor_id = SensorDataHandler.get_sensor_id_from_topic(topic)

        if not sensor_id:
            logger.warning(f"Cannot process message from unknown topic: {topic}")
            return

        AggregationBuffer.accumulate_data(sensor_id, payload)

    except Exception as e:
        logger.error(f"Error handling MQTT message from {topic}: {e}")


def get_buildings_with_sensors():
    """Mendapatkan daftar building beserta sensor-sensornya."""
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
                    'building_id':   row.building_id,
                    'building_code': row.building_code,
                    'sensors':       []
                }

            if row.sensor_id:
                buildings[building_name]['sensors'].append({
                    'sensor_id':   row.sensor_id,
                    'sensor_name': row.sensor_name,
                    'topic':       f"sensor/{row.building_code}/{row.sensor_name}"
                })

        logger.info(f"Retrieved {len(buildings)} buildings with sensors")
        return buildings

    except Exception as e:
        logger.error(f"Error getting buildings with sensors: {e}")
        return {}

    finally:
        session.close()