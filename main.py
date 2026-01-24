from flask import Flask, render_template, jsonify, request
import paho.mqtt.client as mqtt
import json
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool
from datetime import datetime, timedelta, timezone
import threading
import time
import logging
import sys
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

app = Flask(__name__)

BROKER = "10.1.1.55"
PORT = 1883
TOPIC_PATTERN = "sensor/#"
TOPIC_PREDICT = "predict/pub"
TOPIC_PREDICT_RESULT = "predict/result"

DB_CONFIG = {
    "dbname": "energy_monitoring",
    "user": "postgres",
    "password": "nadila",
    "host": "localhost",
    "port": 5432
}

DB_POOL_MINCONN = 1
DB_POOL_MAXCONN = 10
db_pool = None

latest_data = {}

# -------------------- CONFIGURATIONS FOR ROBUSTNESS --------------------
MAX_BUCKETS_PER_SENSOR = 100
FLUSH_INTERVAL_SEC = 15
CLEANUP_INTERVAL_MIN = 5
MAX_RETRY_DB = 3
MQTT_RECONNECT_DELAY_SEC = 5
BUCKET_CUTOFF_SEC = 10
OLD_BUCKET_THRESHOLD_HOURS = 1

# Tarif listrik per kWh (sesuaikan dengan tarif aktual)
TARIF_PER_KWH = 1444.70

# -------------------- LOGGING SETUP --------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('server_pzem.log')
    ]
)
logger = logging.getLogger(__name__)

# -------------------- THREAD SAFETY --------------------
db_write_lock = threading.Lock()
MODEL = None
MODEL_LOCK = threading.Lock()

# --------------------- DATABASE HELPERS ------------------------
def init_db_pool():
    global db_pool
    if db_pool is None:
        try:
            db_pool = ThreadedConnectionPool(
                DB_POOL_MINCONN, DB_POOL_MAXCONN,
                dbname=DB_CONFIG["dbname"],
                user=DB_CONFIG["user"],
                password=DB_CONFIG["password"],
                host=DB_CONFIG["host"],
                port=DB_CONFIG["port"],
                connect_timeout=10
            )
            logger.info("DB pool initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize DB pool: {e}")
            sys.exit(1)

def get_conn():
    if db_pool is None:
        init_db_pool()
    try:
        return db_pool.getconn()
    except Exception as e:
        logger.error(f"Failed to get DB connection: {e}")
        raise

def put_conn(conn):
    if db_pool:
        try:
            db_pool.putconn(conn)
        except Exception as e:
            logger.warning(f"Failed to put back DB connection: {e}")

def query_db_pg(query, args=(), one=False):
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(query, args)
        rows = cur.fetchall()
        return (rows[0] if rows else None) if one else rows
    except Exception as e:
        logger.error(f"DB query error: {e}")
        raise
    finally:
        put_conn(conn)

def execute_db_pg(query, args=()):
    for attempt in range(MAX_RETRY_DB):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(query, args)
            conn.commit()
            return
        except Exception as e:
            logger.warning(f"DB execute attempt {attempt+1} failed: {e}")
            conn.rollback()
            if attempt < MAX_RETRY_DB - 1:
                time.sleep(2 ** attempt)
        finally:
            cur.close()
            put_conn(conn)
    logger.error("DB execute failed after all retries.")

# ------------------- MQTT / SENSOR LOGIC -------------------
def get_sensor_id_from_topic(topic: str):
    try:
        parts = topic.split("/")
        if len(parts) != 3 or parts[0] != "sensor":
            return None
        building_code, sensor_name = parts[1], parts[2]
        row = query_db_pg("""
            SELECT s.id FROM sensors s
            JOIN buildings b ON s.building_id = b.id
            WHERE b.code = %s AND s.name = %s LIMIT 1
        """, (building_code, sensor_name), one=True)
        return row["id"] if row else None
    except Exception as e:
        logger.error(f"Error get_sensor_id_from_topic: {e}")
        return None

def save_sensor_data(sensor_id: int, data: dict):
    """
    Menyimpan data sensor ke database dengan struktur baru
    - Menghilangkan kolom 'cost' dari tabel sensor_readings (dihitung di view)
    - Menambahkan peak_voltage dan peak_current
    """
    required = ('tegangan', 'arus', 'daya', 'energi', 'frekuensi', 'pf')
    if not all(k in data for k in required):
        logger.warning(f"Incomplete data for sensor {sensor_id}, skipping save. Missing: {[k for k in required if k not in data]}")
        return

    ts = data.get('force_timestamp', datetime.utcnow().replace(tzinfo=timezone.utc))

    for attempt in range(MAX_RETRY_DB):
        with db_write_lock:
            conn = get_conn()
            try:
                cur = conn.cursor()
                # Kolom cost TIDAK disimpan di sensor_readings (dihitung di continuous aggregate)
                cur.execute("""
                    INSERT INTO sensor_readings
                    (sensor_id, timestamp, voltage, current, power, energy, frequency, power_factor, peak_voltage, peak_current)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (sensor_id, timestamp) DO UPDATE SET
                      voltage = EXCLUDED.voltage,
                      current = EXCLUDED.current,
                      power = EXCLUDED.power,
                      energy = EXCLUDED.energy,
                      frequency = EXCLUDED.frequency,
                      power_factor = EXCLUDED.power_factor,
                      peak_voltage = EXCLUDED.peak_voltage,
                      peak_current = EXCLUDED.peak_current
                """, (
                    sensor_id, ts,
                    float(data['tegangan']),
                    float(data['arus']),
                    float(data['daya']),
                    float(data['energi']),
                    float(data['frekuensi']),
                    float(data['pf']),
                    float(data['peak_voltage']),
                    float(data['peak_current'])
                ))
                conn.commit()
                logger.info(f"✅ Data saved for sensor {sensor_id} @ {ts}")
                return
            except Exception as e:
                logger.warning(f"Save attempt {attempt+1} failed for sensor {sensor_id}: {e}")
                conn.rollback()
                if attempt < MAX_RETRY_DB - 1:
                    time.sleep(2 ** attempt)
            finally:
                cur.close()
                put_conn(conn)
    logger.error(f"❌ Failed to save data for sensor {sensor_id} after retries.")

# ------------------- THRESHOLD CHECKING & ALARM -------------------
def check_thresholds_and_create_alarm(sensor_id: int, data: dict):
    """
    Cek threshold dan buat alarm event jika ada pelanggaran
    """
    try:
        # Ambil threshold untuk sensor ini
        threshold = query_db_pg("""
            SELECT voltage_min, voltage_max, current_min, current_max
            FROM sensor_thresholds
            WHERE sensor_id = %s
        """, (sensor_id,), one=True)

        if not threshold:
            logger.debug(f"No threshold configured for sensor {sensor_id}")
            return

        voltage = float(data.get('tegangan', 0))
        current = float(data.get('arus', 0))
        
        alarms = []

        # Cek voltage
        if voltage < threshold['voltage_min']:
            alarms.append({
                'parameter': 'voltage',
                'actual_value': voltage,
                'threshold_min': threshold['voltage_min'],
                'threshold_max': threshold['voltage_max'],
                'status': 'under_voltage'
            })
        elif voltage > threshold['voltage_max']:
            alarms.append({
                'parameter': 'voltage',
                'actual_value': voltage,
                'threshold_min': threshold['voltage_min'],
                'threshold_max': threshold['voltage_max'],
                'status': 'over_voltage'
            })

        # Cek current
        if current < threshold['current_min']:
            alarms.append({
                'parameter': 'current',
                'actual_value': current,
                'threshold_min': threshold['current_min'],
                'threshold_max': threshold['current_max'],
                'status': 'under_current'
            })
        elif current > threshold['current_max']:
            alarms.append({
                'parameter': 'current',
                'actual_value': current,
                'threshold_min': threshold['current_min'],
                'threshold_max': threshold['current_max'],
                'status': 'over_current'
            })

        # Simpan alarm ke database
        if alarms:
            conn = get_conn()
            try:
                cur = conn.cursor()
                for alarm in alarms:
                    cur.execute("""
                        INSERT INTO alarm_events
                        (sensor_id, timestamp, parameter, actual_value, threshold_min, threshold_max, status)
                        VALUES (%s, NOW(), %s, %s, %s, %s, %s)
                    """, (
                        sensor_id,
                        alarm['parameter'],
                        alarm['actual_value'],
                        alarm['threshold_min'],
                        alarm['threshold_max'],
                        alarm['status']
                    ))
                conn.commit()
                logger.warning(f"⚠️ Alarm created for sensor {sensor_id}: {alarms}")
            except Exception as e:
                logger.error(f"Failed to create alarm: {e}")
                conn.rollback()
            finally:
                cur.close()
                put_conn(conn)

    except Exception as e:
        logger.error(f"Error checking thresholds: {e}")

# ------------------- AGGREGATION BUFFER (TIME-BUCKETED) -------------------
agg_buffer = {}
agg_lock = threading.Lock()

def accumulate_sensor_data(sensor_id: int, data: dict):
    """
    Akumulasi data sensor dalam bucket waktu per menit
    """
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    bucket_time = now.replace(second=0, microsecond=0)
    bucket_ts = bucket_time.timestamp()

    with agg_lock:
        if sensor_id not in agg_buffer:
            agg_buffer[sensor_id] = {}

        # Enforce bucket limit
        if len(agg_buffer[sensor_id]) >= MAX_BUCKETS_PER_SENSOR:
            oldest_key = min(agg_buffer[sensor_id].keys())
            del agg_buffer[sensor_id][oldest_key]
            logger.warning(f"Bucket limit exceeded for sensor {sensor_id}, removed oldest bucket.")

        if bucket_ts not in agg_buffer[sensor_id]:
            agg_buffer[sensor_id][bucket_ts] = {
                "sums": {k: 0.0 for k in ['tegangan', 'arus', 'daya', 'energi', 'frekuensi', 'pf']},
                "count": 0,
                "timestamp_obj": bucket_time,
                "peak_voltage": float('-inf'),
                "peak_current": float('-inf')
            }

        buf = agg_buffer[sensor_id][bucket_ts]

        try:
            # Hitung energi berdasarkan daya (kWh)
            daya = float(data.get('daya', 0.0))
            # Asumsi sampling setiap 10 detik
            energi_wh = daya * (10.0 / 3600.0)  # Wh
            energi_kwh = energi_wh / 1000.0      # kWh

            # Akumulasi sums
            for k in ['tegangan', 'arus', 'daya', 'frekuensi', 'pf']:
                buf['sums'][k] += float(data.get(k, 0.0))
            buf['sums']['energi'] += energi_kwh
            buf['count'] += 1

            # Update peak voltage dan current
            voltage = float(data.get('tegangan', 0.0))
            current = float(data.get('arus', 0.0))
            buf['peak_voltage'] = max(buf['peak_voltage'], voltage)
            buf['peak_current'] = max(buf['peak_current'], current)

            logger.debug(f"📊 Accumulated data for sensor {sensor_id}, bucket {bucket_time.strftime('%H:%M')}, count: {buf['count']}, peak_v: {buf['peak_voltage']:.2f}V, peak_c: {buf['peak_current']:.2f}A")
        except Exception as e:
            logger.error(f"Error accumulating data for sensor {sensor_id}: {e}")

def flush_buffer_buckets(sensor_id: int):
    """
    Flush bucket yang sudah matang (lebih dari BUCKET_CUTOFF_SEC)
    """
    now_ts = time.time()
    cutoff_time = now_ts - BUCKET_CUTOFF_SEC

    with agg_lock:
        if sensor_id not in agg_buffer:
            return

        bucket_keys = list(agg_buffer[sensor_id].keys())
        for b_key in bucket_keys:
            if b_key > cutoff_time:
                continue

            buf = agg_buffer[sensor_id][b_key]
            count = buf['count']
            if count > 0:
                sums = buf['sums']
                payload = {
                    "tegangan": sums['tegangan'] / count,
                    "arus": sums['arus'] / count,
                    "daya": sums['daya'] / count,
                    "energi": sums['energi'],  # Total kWh
                    "frekuensi": sums['frekuensi'] / count,
                    "pf": sums['pf'] / count,
                    "force_timestamp": buf['timestamp_obj'],
                    "peak_voltage": buf['peak_voltage'],
                    "peak_current": buf['peak_current']
                }
                try:
                    save_sensor_data(sensor_id, payload)
                    # Check thresholds setelah save
                    check_thresholds_and_create_alarm(sensor_id, payload)
                except Exception as e:
                    logger.error(f"Flush error for sensor {sensor_id}: {e}")
            del agg_buffer[sensor_id][b_key]

def cleanup_old_buckets():
    """Remove buckets older than threshold to free memory."""
    cutoff_ts = time.time() - (OLD_BUCKET_THRESHOLD_HOURS * 3600)
    with agg_lock:
        for sensor_id in list(agg_buffer.keys()):
            old_keys = [k for k in agg_buffer[sensor_id] if k < cutoff_ts]
            for k in old_keys:
                del agg_buffer[sensor_id][k]
                logger.info(f"🧹 Cleaned old bucket for sensor {sensor_id} @ {datetime.fromtimestamp(k)}")
            if not agg_buffer[sensor_id]:
                del agg_buffer[sensor_id]

def flush_worker():
    """Background scheduler untuk flush dan cleanup"""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=lambda: [flush_buffer_buckets(sid) for sid in list(agg_buffer.keys())],
        trigger=IntervalTrigger(seconds=FLUSH_INTERVAL_SEC),
        id='flush_job',
        name='Flush matured buckets'
    )
    scheduler.add_job(
        func=cleanup_old_buckets,
        trigger=IntervalTrigger(minutes=CLEANUP_INTERVAL_MIN),
        id='cleanup_job',
        name='Cleanup old buckets'
    )
    scheduler.start()
    logger.info("🚀 Flush worker and cleanup scheduler started.")

# ---------------------- MQTT HANDLER -------------------
def handle_sensor_message(sensor_id: int, data: dict):
    try:
        accumulate_sensor_data(sensor_id, data)
    except Exception as e:
        logger.error(f"Failed to handle sensor message: {e}")

def handle_message(topic: str, data: dict, client: mqtt.Client):
    latest_data[topic] = data
    sensor_id = get_sensor_id_from_topic(topic)
    if sensor_id:
        handle_sensor_message(sensor_id, data)
    elif topic == TOPIC_PREDICT:
        pass
    else:
        logger.debug(f"Unrecognized topic: {topic}")

# ---------------------- MQTT CALLBACK ------------------
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logger.info("✅ Connected to MQTT Broker")
        client.subscribe([(TOPIC_PATTERN, 0), (TOPIC_PREDICT, 0)])
    else:
        logger.warning(f"❌ MQTT connect failed with rc: {rc}, retrying in {MQTT_RECONNECT_DELAY_SEC}s")
        time.sleep(MQTT_RECONNECT_DELAY_SEC)
        client.reconnect()

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode()
        data = json.loads(payload)
        handle_message(msg.topic, data, client)
    except Exception as e:
        logger.error(f"Error in on_message: {e}")

def start_mqtt(loop_forever=False):
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(BROKER, PORT, 60)
        client.loop_start()
        logger.info("🔌 MQTT client started.")
        return client
    except Exception as e:
        logger.error(f"Failed to start MQTT: {e}")
        return None

# ------------------------ GET BUILDINGS & SENSORS ------------------------
def get_buildings_with_sensors():
    try:
        rows = query_db_pg("""
            SELECT b.id as building_id, b.name as building_name, b.code as building_code,
                   s.id as sensor_id, s.name as sensor_name
            FROM buildings b LEFT JOIN sensors s ON b.id = s.building_id
            ORDER BY b.id;
        """)
        buildings = {}
        for row in rows:
            building_name = row['building_name']
            if building_name not in buildings:
                buildings[building_name] = {
                    'building_id': row['building_id'],
                    'building_code': row['building_code'],
                    'sensors': []
                }
            if row['sensor_id']:
                buildings[building_name]['sensors'].append({
                    'sensor_id': row['sensor_id'],
                    'sensor_name': row['sensor_name'],
                    'topic': f"sensor/{row['building_code']}/{row['sensor_name']}"
                })
        return buildings
    except Exception as e:
        logger.error(f"Error getting buildings: {e}")
        return {}

# ------------------------ API ENDPOINTS ------------------------
@app.route("/")
def index_page():
    return render_template("view_mode.html")

@app.route("/realtime")
def get_realtime():
    """
    Endpoint realtime dengan data bulan ini dari continuous aggregate view_daily_energy
    """
    now = datetime.utcnow().replace(tzinfo=timezone.utc)

    # Awal dan akhir bulan (UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.month == 12:
        next_month = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0)
    else:
        next_month = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0)
    month_end = next_month - timedelta(seconds=1)

    buildings_data = get_buildings_with_sensors()
    departments = []

    total_energy_all = 0.0
    total_cost_all = 0.0

    for building_name, info in buildings_data.items():
        phases = {}
        total_energy = 0.0
        total_cost = 0.0

        for sensor in info['sensors']:
            topic = f"sensor/{info['building_code']}/{sensor['sensor_name']}"
            sensor_data = latest_data.get(topic)

            phase_key = sensor['sensor_name'][-1].lower() if sensor['sensor_name'][-1].lower() in ['r', 's', 't'] else sensor['sensor_name']

            if not sensor_data:
                sensor_data = {"tegangan": 0, "arus": 0, "daya": 0, "energi": 0}

            phases[phase_key] = {
                "voltage": float(sensor_data.get("tegangan", 0.0)),
                "current": float(sensor_data.get("arus", 0.0)),
                "power": float(sensor_data.get("daya", 0.0)),
                "energy": float(sensor_data.get("energi", 0.0))
            }

            # Ambil data bulanan dari continuous aggregate view
            row = query_db_pg("""
                SELECT 
                    SUM(total_energy_kwh) as total_energy,
                    SUM(total_cost) as total_cost
                FROM view_daily_energy
                WHERE sensor_id = %s
                  AND date >= %s AND date < %s
            """, (
                sensor['sensor_id'],
                month_start,
                next_month
            ), one=True)

            if row:
                total_energy += float(row["total_energy"] or 0)
                total_cost += float(row["total_cost"] or 0)

        departments.append({
            "id": info['building_code'],
            "name": building_name,
            "phases": phases,
            "total": {
                "total_energy": round(total_energy, 4),
                "total_cost": round(total_cost, 2)
            }
        })

        total_energy_all += total_energy
        total_cost_all += total_cost

    summary = {
        "overall_energy": round(total_energy_all, 4),
        "overall_cost": round(total_cost_all, 2),
        "month": now.strftime("%B"),
        "year": now.year
    }

    return jsonify({
        "success": True,
        "timestamp": now.isoformat(),
        "departments": departments,
        "summary": summary
    })

@app.route("/admin")
def admin_page():
    return render_template("realtime_fetch.html")

@app.route("/dashboard-admin", methods=["GET"])
def get_dashboard():
    """Dashboard admin dengan data realtime"""
    field = request.args.get("field")

    building_stats = {}
    buildings_data = get_buildings_with_sensors()

    for building_name, info in buildings_data.items():
        for sensor in info['sensors']:
            topic = f"sensor/{info['building_code']}/{sensor['sensor_name']}"
            sensor_data = latest_data.get(topic)

            if not sensor_data:
                continue

            if building_name not in building_stats:
                building_stats[building_name] = {
                    "sums": {},
                    "count": 0
                }

            stats = building_stats[building_name]
            stats["count"] += 1

            if field:
                if field.lower() in ["energi", "energy"]:
                    daya_val = float(sensor_data.get("daya", 0) or 0)
                    energi_val = (daya_val * 3) / 3600 / 1000
                    stats["sums"]["daya"] = stats["sums"].get("daya", 0) + daya_val
                    stats["sums"]["energi"] = stats["sums"].get("energi", 0) + energi_val
                else:
                    val = float(sensor_data.get(field, 0) or 0)
                    stats["sums"][field] = stats["sums"].get(field, 0) + val
            else:
                for k, v in sensor_data.items():
                    try:
                        stats["sums"][k] = stats["sums"].get(k, 0) + float(v or 0)
                    except Exception:
                        pass

    results = {}
    for building_name, stats in building_stats.items():
        count = stats["count"]
        if count > 0:
            daya_total = stats["sums"].get("daya", 0.0)

            averaged = {}
            for k, v in stats["sums"].items():
                key = k.lower()
                if key in ["daya", "power"]:
                    averaged[k] = round(daya_total, 3)
                elif key in ["energi", "energy"]:
                    energi_val = (daya_total * 3) / 3600 / 1000
                    if 0 < energi_val < 0.001:
                        averaged[k] = float(f"{energi_val:.7e}")
                    else:
                        averaged[k] = round(energi_val, 6)
                else:
                    averaged[k] = round(v / count, 3)

            results[building_name] = averaged
        else:
            results[building_name] = None

    return jsonify(results)

@app.route("/index/energy-usage")
def energy_usage():
    """
    Energy usage per jam menggunakan continuous aggregate view_hourly_energy
    """
    buildings_data = get_buildings_with_sensors()
    datasets = []
    labels = []

    for building_name, info in buildings_data.items():
        energy_per_hour = {}

        for sensor_info in info['sensors']:
            sensor_id = sensor_info['sensor_id']

            # Gunakan continuous aggregate view_hourly_energy
            rows = query_db_pg("""
                SELECT 
                    to_char(date, 'HH24:MI') AS jam,
                    total_kwh
                FROM view_hourly_energy
                WHERE sensor_id = %s
                ORDER BY date DESC
                LIMIT 24
            """, (sensor_id,))

            for row in rows:
                jam = row["jam"]
                energi = float(row["total_kwh"] or 0)
                energy_per_hour[jam] = energy_per_hour.get(jam, 0) + energi

        sorted_times = sorted(energy_per_hour.keys())
        usage = [energy_per_hour[j] for j in sorted_times]

        datasets.append({
            "building": building_name,
            "usage": usage
        })

        if not labels and sorted_times:
            labels = sorted_times

    return jsonify({
        "labels": labels,
        "datasets": datasets
    })

@app.route("/index/energy-pie")
def energy_pie():
    """
    Pie chart energy consumption menggunakan continuous aggregate
    """
    period = request.args.get('period', 'minggu')

    end_date = datetime.utcnow().replace(tzinfo=timezone.utc)
    if period == 'minggu':
        start_date = end_date - timedelta(days=7)
        period_label = "Minggu Ini"
    else:
        start_date = end_date - timedelta(days=30)
        period_label = "Bulan Ini"

    labels = []
    values = []
    total_energy = 0.0

    buildings_data = get_buildings_with_sensors()

    for building_name, info in buildings_data.items():
        building_total = 0.0

        for sensor_info in info['sensors']:
            sensor_id = sensor_info['sensor_id']

            # Gunakan continuous aggregate view_daily_energy
            row = query_db_pg("""
                SELECT SUM(total_energy_kwh) AS total
                FROM view_daily_energy
                WHERE sensor_id = %s AND date >= %s AND date <= %s
            """, (sensor_id, start_date, end_date), one=True)

            if row and row["total"] is not None:
                building_total += float(row["total"])

        labels.append(building_name)
        values.append(round(building_total, 4))
        total_energy += building_total

    return jsonify({
        "labels": labels,
        "values": values,
        "period": period,
        "period_label": period_label,
        "total_energy": round(total_energy, 4),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat()
    })

@app.route("/index/stats")
def get_stats():
    """
    Statistics menggunakan continuous aggregate view_daily_energy
    """
    period = request.args.get('period', 'minggu')

    end_date = datetime.utcnow().replace(tzinfo=timezone.utc)
    if period == 'minggu':
        start_date = end_date - timedelta(days=7)
    else:
        start_date = end_date - timedelta(days=30)

    total_energy = 0.0
    total_cost = 0.0

    buildings_data = get_buildings_with_sensors()

    for building_name, info in buildings_data.items():
        for sensor_info in info['sensors']:
            sensor_id = sensor_info['sensor_id']

            # Gunakan continuous aggregate view_daily_energy
            row = query_db_pg("""
                SELECT 
                    SUM(total_energy_kwh) AS energy,
                    SUM(total_cost) AS cost
                FROM view_daily_energy
                WHERE sensor_id = %s AND date >= %s AND date <= %s
            """, (sensor_id, start_date, end_date), one=True)

            if row:
                total_energy += float(row["energy"] or 0)
                total_cost += float(row["cost"] or 0)

    return jsonify({
        "period": period,
        "total_energy": round(total_energy, 4),
        "total_cost": round(total_cost, 2),
        "energy_formatted": f"{total_energy:,.4f} kWh",
        "cost_formatted": f"IDR {total_cost:,.2f}",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat()
    })

# -------------------- ADDITIONAL API ENDPOINTS --------------------
@app.route("/api/alarms", methods=["GET"])
def get_alarms():
    """Get recent alarm events"""
    limit = request.args.get('limit', 50, type=int)
    sensor_id = request.args.get('sensor_id', type=int)
    
    query = """
        SELECT 
            ae.id, ae.sensor_id, ae.timestamp, ae.parameter,
            ae.actual_value, ae.threshold_min, ae.threshold_max, ae.status,
            s.name as sensor_name, b.name as building_name
        FROM alarm_events ae
        JOIN sensors s ON ae.sensor_id = s.id
        JOIN buildings b ON s.building_id = b.id
    """
    
    params = []
    if sensor_id:
        query += " WHERE ae.sensor_id = %s"
        params.append(sensor_id)
    
    query += " ORDER BY ae.timestamp DESC LIMIT %s"
    params.append(limit)
    
    alarms = query_db_pg(query, tuple(params))
    
    return jsonify({
        "success": True,
        "alarms": [dict(alarm) for alarm in alarms]
    })

@app.route("/api/thresholds/<int:sensor_id>", methods=["GET", "PUT"])
def manage_thresholds(sensor_id):
    """Get or update sensor thresholds"""
    if request.method == "GET":
        threshold = query_db_pg("""
            SELECT * FROM sensor_thresholds WHERE sensor_id = %s
        """, (sensor_id,), one=True)
        
        if threshold:
            return jsonify({
                "success": True,
                "threshold": dict(threshold)
            })
        else:
            return jsonify({
                "success": False,
                "message": "Threshold not found"
            }), 404
    
    elif request.method == "PUT":
        data = request.get_json()
        
        try:
            execute_db_pg("""
                INSERT INTO sensor_thresholds 
                (sensor_id, voltage_min, voltage_max, current_min, current_max)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (sensor_id) DO UPDATE SET
                    voltage_min = EXCLUDED.voltage_min,
                    voltage_max = EXCLUDED.voltage_max,
                    current_min = EXCLUDED.current_min,
                    current_max = EXCLUDED.current_max,
                    created_at = NOW()
            """, (
                sensor_id,
                data.get('voltage_min'),
                data.get('voltage_max'),
                data.get('current_min'),
                data.get('current_max')
            ))
            
            return jsonify({
                "success": True,
                "message": "Threshold updated successfully"
            })
        except Exception as e:
            logger.error(f"Failed to update threshold: {e}")
            return jsonify({
                "success": False,
                "message": str(e)
            }), 500

@app.route("/api/sensors", methods=["GET"])
def get_all_sensors():
    """Get all sensors with their building info"""
    sensors = query_db_pg("""
        SELECT 
            s.id, s.name as sensor_name, s.building_id,
            b.name as building_name, b.code as building_code
        FROM sensors s
        JOIN buildings b ON s.building_id = b.id
        ORDER BY b.name, s.name
    """)
    
    return jsonify({
        "success": True,
        "sensors": [dict(sensor) for sensor in sensors]
    })

@app.route("/api/refresh-views", methods=["POST"])
def refresh_continuous_aggregates():
    """Manually refresh continuous aggregate views"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Refresh view_daily_energy
        cur.execute("CALL refresh_continuous_aggregate('view_daily_energy', NULL, NULL);")
        
        # Refresh view_hourly_energy
        cur.execute("CALL refresh_continuous_aggregate('view_hourly_energy', NULL, NULL);")
        
        conn.commit()
        cur.close()
        put_conn(conn)
        
        logger.info("✅ Continuous aggregates refreshed manually")
        
        return jsonify({
            "success": True,
            "message": "Views refreshed successfully"
        })
    except Exception as e:
        logger.error(f"Failed to refresh views: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

# ------------------------ MAIN STARTUP ------------------------
if __name__ == '__main__':
    # Init DB pool
    init_db_pool()

    # Start MQTT client
    mqtt_client = start_mqtt(loop_forever=False)
    
    # Start flush worker
    threading.Thread(target=flush_worker, daemon=True).start()

    # Run Flask
    logger.info("🚀 Starting Flask server on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)