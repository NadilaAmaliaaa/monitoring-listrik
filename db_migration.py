import psycopg2
from psycopg2 import sql

DB_CONFIG = {
    "dbname": "energy_monitoring",
    "user": "postgres",
    "password": "nadila",
    "host": "localhost",
    "port": 5432
}


def migrate():
    print("\n🚀 Menjalankan migrasi database TimescaleDB...")

    # Koneksi awal
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # 1️⃣ Aktifkan ekstensi TimescaleDB
    print("📦 Mengaktifkan ekstensi TimescaleDB...")
    cur.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")

    # 2️⃣ Buat tabel buildings
    print("🏢 Membuat tabel buildings...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS buildings (
            id SERIAL PRIMARY KEY,
            code VARCHAR(50) NOT NULL UNIQUE,
            name VARCHAR(100) NOT NULL
        );
    """)

    # 3️⃣ Buat tabel sensors
    print("📡 Membuat tabel sensors...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sensors (
            id SERIAL PRIMARY KEY,
            building_id INT NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
            name VARCHAR(50) NOT NULL
        );
    """)

    # 4️⃣ Buat tabel sensor_readings (hypertable)
    print("📊 Membuat tabel sensor_readings...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sensor_readings (
            sensor_id INT NOT NULL REFERENCES sensors(id) ON DELETE CASCADE,
            timestamp TIMESTAMPTZ NOT NULL,
            voltage DOUBLE PRECISION,
            current DOUBLE PRECISION,
            power DOUBLE PRECISION,
            energy DOUBLE PRECISION,
            frequency DOUBLE PRECISION,
            power_factor DOUBLE PRECISION,
            peak_voltage DOUBLE PRECISION,
            peak_current DOUBLE PRECISION,
            PRIMARY KEY (sensor_id, timestamp)
        );
    """)

    # 5️⃣ Jadikan hypertable
    print("⚡ Mengonversi sensor_readings menjadi hypertable...")
    cur.execute("""
        SELECT create_hypertable('sensor_readings', 'timestamp', if_not_exists => TRUE);
    """)

    # 6️⃣ Buat tabel sensor_thresholds
    print("⚠️ Membuat tabel sensor_thresholds...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sensor_thresholds (
            id SERIAL PRIMARY KEY,
            sensor_id INT NOT NULL REFERENCES sensors(id) ON DELETE CASCADE,
            voltage_min DOUBLE PRECISION,
            voltage_max DOUBLE PRECISION,
            current_min DOUBLE PRECISION,
            current_max DOUBLE PRECISION,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(sensor_id)
        );
    """)

    # 7️⃣ Buat tabel alarm_events
    print("🚨 Membuat tabel alarm_events...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS alarm_events (
            id SERIAL PRIMARY KEY,
            sensor_id INT NOT NULL REFERENCES sensors(id) ON DELETE CASCADE,
            timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            parameter VARCHAR(50) NOT NULL,
            actual_value DOUBLE PRECISION,
            threshold_min DOUBLE PRECISION,
            threshold_max DOUBLE PRECISION,
            status VARCHAR(20) NOT NULL
        );
    """)

    # 8️⃣ Index tambahan untuk performa
    print("🔍 Membuat index...")
    # cur.execute("""
    #     CREATE INDEX IF NOT EXISTS idx_sensor_time
    #     ON sensor_readings (sensor_id, timestamp DESC);
    # """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_alarm_sensor_time
        ON alarm_events (sensor_id, timestamp DESC);
    """)

    conn.commit()
    cur.close()
    conn.close()

    # 9️⃣ Buat continuous aggregate view_daily_energy
    print("📈 Membuat continuous aggregate view_daily_energy...")
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    cur = conn.cursor()
    
    cur.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS view_daily_energy
        WITH (timescaledb.continuous) AS
        SELECT 
            time_bucket('1 day', timestamp) AS date,
            sensor_id,
            SUM(energy) AS total_energy_kwh,
            AVG(power) AS avg_power,
            MAX(power) AS peak_power,
            SUM(energy * 1444.70) AS total_cost
        FROM sensor_readings
        GROUP BY date, sensor_id
        WITH NO DATA;
    """)
    # SUM(power) * (1.0/60) / 1000 AS energy_kwh

    # 🔟 Buat continuous aggregate view_hourly_energy
    print("📈 Membuat continuous aggregate view_hourly_energy...")
    cur.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS view_hourly_energy
        WITH (timescaledb.continuous) AS
        SELECT 
            time_bucket('1 hour', timestamp) AS date,
            sensor_id,
            AVG(power) AS power,
            AVG(power) AS avg_power,
            MAX(power) AS peak_power,
            SUM(energy) AS total_kwh,
            SUM(energy * 1444.70) AS total_cost
        FROM sensor_readings
        GROUP BY date, sensor_id
        WITH NO DATA;
    """)

    cur.close()
    conn.close()

    # 1️⃣1️⃣ Tambahkan refresh policy untuk view_daily_energy
    print("🕒 Menambahkan refresh policy untuk view_daily_energy...")
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM timescaledb_information.jobs j
                WHERE j.proc_name = 'policy_refresh_continuous_aggregate'
                AND j.config->>'mat_hypertable_id' = (
                    SELECT format('%I.%I', materialization_hypertable_schema, materialization_hypertable_name)::regclass::oid::text
                    FROM timescaledb_information.continuous_aggregates
                    WHERE view_name = 'view_daily_energy'
                )
            ) THEN
                PERFORM add_continuous_aggregate_policy(
                    'view_daily_energy',
                    start_offset => INTERVAL '7 days',
                    end_offset   => INTERVAL '1 minute',
                    schedule_interval => INTERVAL '5 minutes'
                );
            END IF;
        END
        $$;
    """)

    # 1️⃣2️⃣ Tambahkan refresh policy untuk view_hourly_energy
    print("🕒 Menambahkan refresh policy untuk view_hourly_energy...")
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM timescaledb_information.jobs j
                WHERE j.proc_name = 'policy_refresh_continuous_aggregate'
                AND j.config->>'mat_hypertable_id' = (
                    SELECT format('%I.%I', materialization_hypertable_schema, materialization_hypertable_name)::regclass::oid::text
                    FROM timescaledb_information.continuous_aggregates
                    WHERE view_name = 'view_hourly_energy'
                )
            ) THEN
                PERFORM add_continuous_aggregate_policy(
                    'view_hourly_energy',
                    start_offset => INTERVAL '3 days',
                    end_offset   => INTERVAL '1 minute',
                    schedule_interval => INTERVAL '5 minutes'
                );
            END IF;
        END
        $$;
    """)

    conn.commit()
    cur.close()
    conn.close()

    print("✅ Migrasi selesai!")


def seed():
    print("\n🌱 Menjalankan seeder...")
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM buildings;")
    if cur.fetchone()[0] > 0:
        print("ℹ️ Seeder dilewati: data sudah ada.")
        conn.close()
        return

    building_data = [
        ("Departement Pusat", "department1"),
        ("Departement Mesin", "department2"),
        ("Departement Elektronika", "department3"),
        ("Departement Otomotif", "department4"),
        ("Departement TI", "department5"),
        ("Departement Manajemen", "department6"),
        ("Departement Sipil", "department7")
    ]

    for name, code in building_data:
        cur.execute(
            "INSERT INTO buildings (name, code) VALUES (%s, %s) RETURNING id;",
            (name, code)
        )
        building_id = cur.fetchone()[0]
        
        # Insert sensors
        for i in range(1, 4):
            cur.execute(
                "INSERT INTO sensors (building_id, name) VALUES (%s, %s) RETURNING id;",
                (building_id, f"PZEM{i}")
            )
            sensor_id = cur.fetchone()[0]
            
            # Insert default thresholds
            cur.execute("""
                INSERT INTO sensor_thresholds (sensor_id, voltage_min, voltage_max, current_min, current_max)
                VALUES (%s, 200, 240, 0, 100);
            """, (sensor_id,))

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Seeder selesai: gedung, sensor, dan threshold berhasil dibuat.")


if __name__ == "__main__":
    migrate()
    seed()