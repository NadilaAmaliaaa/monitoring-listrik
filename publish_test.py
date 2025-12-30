#!/usr/bin/env python3
import paho.mqtt.client as mqtt
import json
import time
import random
from datetime import datetime
import logging

# ==================== CONFIGURATION ====================
BROKER = "192.168.1.5"
PORT = 1883
PUBLISH_INTERVAL = 10  # Kirim data setiap 10 detik

# Daftar building dan sensor sesuai dengan seeder database
BUILDINGS = [
    {
        "code": "department1",
        "name": "Departement Pusat",
        "sensors": ["PZEM1", "PZEM2", "PZEM3"]
    },
    {
        "code": "department2",
        "name": "Departement Mesin",
        "sensors": ["PZEM1", "PZEM2", "PZEM3"]
    },
    {
        "code": "department3",
        "name": "Departement Elektronika",
        "sensors": ["PZEM1", "PZEM2", "PZEM3"]
    },
    {
        "code": "department4",
        "name": "Departement Otomotif",
        "sensors": ["PZEM1", "PZEM2", "PZEM3"]
    },
    {
        "code": "department5",
        "name": "Departement TI",
        "sensors": ["PZEM1", "PZEM2", "PZEM3"]
    },
    {
        "code": "department6",
        "name": "Departement Manajemen",
        "sensors": ["PZEM1", "PZEM2", "PZEM3"]
    },
    {
        "code": "department7",
        "name": "Departement Sipil",
        "sensors": ["PZEM1", "PZEM2", "PZEM3"]
    }
]

# Range nilai sensor yang realistis
SENSOR_RANGES = {
    "tegangan": (215.0, 235.0),      # Voltage: 215-235V (normal range)
    "arus": (5.0, 50.0),              # Current: 5-50A
    "daya": (1000.0, 10000.0),        # Power: 1-10 kW
    "frekuensi": (49.8, 50.2),        # Frequency: 49.8-50.2 Hz
    "pf": (0.85, 1.0)                 # Power Factor: 0.85-1.0
}

# Simulasi kondisi abnormal (untuk testing alarm)
SIMULATE_ANOMALY = False  # Set True untuk test alarm
ANOMALY_PROBABILITY = 0.1  # 10% chance anomaly terjadi

# ==================== LOGGING SETUP ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('mqtt_publisher.log')
    ]
)
logger = logging.getLogger(__name__)

# ==================== MQTT CALLBACKS ====================
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logger.info(f"✅ Connected to MQTT Broker at {BROKER}:{PORT}")
    else:
        logger.error(f"❌ Failed to connect, return code {rc}")

def on_publish(client, userdata, mid):
    logger.debug(f"📤 Message {mid} published")

def on_disconnect(client, userdata, rc):
    if rc != 0:
        logger.warning(f"⚠️ Unexpected disconnection. Reconnecting...")

# ==================== DATA GENERATION ====================
def generate_sensor_data(building_code, sensor_name, simulate_anomaly=False):
    """
    Generate data sensor yang realistis
    """
    # Generate nilai normal
    if simulate_anomaly and random.random() < ANOMALY_PROBABILITY:
        # Simulasi anomaly
        tegangan = random.choice([
            random.uniform(180.0, 200.0),  # Under voltage
            random.uniform(245.0, 260.0)   # Over voltage
        ])
        arus = random.choice([
            random.uniform(0.5, 3.0),      # Under current
            random.uniform(80.0, 120.0)    # Over current
        ])
        logger.warning(f"⚠️ Generating ANOMALY data for {building_code}/{sensor_name}")
    else:
        # Nilai normal
        tegangan = random.uniform(*SENSOR_RANGES["tegangan"])
        arus = random.uniform(*SENSOR_RANGES["arus"])
    
    # Hitung daya (P = V × I × PF)
    pf = random.uniform(*SENSOR_RANGES["pf"])
    daya = tegangan * arus * pf
    
    # Frekuensi
    frekuensi = random.uniform(*SENSOR_RANGES["frekuensi"])
    
    # Peak values (sedikit lebih tinggi dari nilai rata-rata)
    peak_voltage = tegangan * random.uniform(1.0, 1.05)
    peak_current = arus * random.uniform(1.0, 1.05)
    
    # Energi akan dihitung di backend (daya × waktu)
    # Tapi kita kasih nilai dummy untuk kompatibilitas
    energi = (daya * 10.0) / 3600.0 / 1000.0  # kWh untuk 10 detik sampling
    
    data = {
        "tegangan": round(tegangan, 2),
        "arus": round(arus, 2),
        "daya": round(daya, 2),
        "energi": round(energi, 6),
        "frekuensi": round(frekuensi, 2),
        "pf": round(pf, 3),
        "peak_voltage": round(peak_voltage, 2),
        "peak_current": round(peak_current, 2),
        "timestamp": datetime.now().isoformat()
    }
    
    return data

# ==================== PUBLISHING FUNCTIONS ====================
def publish_single_sensor(client, building_code, sensor_name):
    """
    Publish data untuk satu sensor
    """
    topic = f"sensor/{building_code}/{sensor_name}"
    data = generate_sensor_data(building_code, sensor_name, SIMULATE_ANOMALY)
    
    try:
        payload = json.dumps(data)
        result = client.publish(topic, payload, qos=0)
        
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.info(f"📡 Published to {topic}: V={data['tegangan']}V, I={data['arus']}A, P={data['daya']}W")
        else:
            logger.error(f"❌ Failed to publish to {topic}")
    except Exception as e:
        logger.error(f"❌ Error publishing to {topic}: {e}")

def publish_all_sensors(client):
    """
    Publish data untuk semua sensor di semua building
    """
    logger.info("=" * 70)
    logger.info(f"🔄 Publishing data for all sensors at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)
    
    total_published = 0
    
    for building in BUILDINGS:
        building_code = building["code"]
        building_name = building["name"]
        
        logger.info(f"🏢 Building: {building_name} ({building_code})")
        
        for sensor_name in building["sensors"]:
            publish_single_sensor(client, building_code, sensor_name)
            total_published += 1
            time.sleep(0.1)  # Small delay to prevent flooding
    
    logger.info(f"✅ Published {total_published} sensor readings")
    logger.info("")

# ==================== TEST MODES ====================
def test_single_publish(client):
    """
    Test mode: publish sekali saja untuk semua sensor
    """
    logger.info("🧪 TEST MODE: Single publish for all sensors")
    publish_all_sensors(client)
    logger.info("✅ Test completed")

def test_continuous_publish(client, duration_minutes=5):
    """
    Test mode: publish kontinyu selama durasi tertentu
    """
    logger.info(f"🧪 TEST MODE: Continuous publish for {duration_minutes} minutes")
    logger.info(f"⏱️ Publish interval: {PUBLISH_INTERVAL} seconds")
    
    start_time = time.time()
    end_time = start_time + (duration_minutes * 60)
    iteration = 0
    
    try:
        while time.time() < end_time:
            iteration += 1
            logger.info(f"📊 Iteration #{iteration}")
            publish_all_sensors(client)
            
            remaining = end_time - time.time()
            if remaining > 0:
                sleep_time = min(PUBLISH_INTERVAL, remaining)
                logger.info(f"💤 Sleeping for {sleep_time:.1f} seconds...")
                time.sleep(sleep_time)
        
        logger.info(f"✅ Test completed after {iteration} iterations")
    except KeyboardInterrupt:
        logger.info("⏹️ Test stopped by user")

def test_stress_publish(client, count=100):
    """
    Test mode: publish banyak data sekaligus untuk stress test
    """
    logger.info(f"🧪 TEST MODE: Stress test with {count} rapid publishes per sensor")
    
    for i in range(count):
        logger.info(f"📊 Stress iteration #{i+1}/{count}")
        publish_all_sensors(client)
        time.sleep(0.5)  # 500ms delay
    
    logger.info("✅ Stress test completed")

def test_anomaly_publish(client):
    """
    Test mode: publish data dengan anomaly untuk test alarm system
    """
    global SIMULATE_ANOMALY
    logger.info("🧪 TEST MODE: Publishing anomaly data to test alarm system")
    
    SIMULATE_ANOMALY = True
    
    # Publish 5 kali dengan kemungkinan anomaly tinggi
    for i in range(5):
        logger.info(f"📊 Anomaly test iteration #{i+1}/5")
        publish_all_sensors(client)
        time.sleep(PUBLISH_INTERVAL)
    
    SIMULATE_ANOMALY = False
    logger.info("✅ Anomaly test completed")

# ==================== MAIN PROGRAM ====================
def main():
    """
    Main program dengan menu pilihan test mode
    """
    print("=" * 70)
    print("🔌 MQTT Test Publisher for Energy Monitoring System")
    print("=" * 70)
    print(f"📍 Broker: {BROKER}:{PORT}")
    print(f"🏢 Buildings: {len(BUILDINGS)}")
    print(f"📡 Total sensors: {len(BUILDINGS) * 3}")
    print("=" * 70)
    print("\nSelect test mode:")
    print("1. Single publish (publish once for all sensors)")
    print("2. Continuous publish (publish every N seconds)")
    print("3. Stress test (rapid fire publishing)")
    print("4. Anomaly test (test alarm system)")
    print("5. Production mode (run forever)")
    print("=" * 70)
    
    try:
        choice = input("Enter your choice (1-5): ").strip()
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        return
    
    # Create MQTT client
    client = mqtt.Client(client_id=f"test_publisher_{int(time.time())}")
    client.on_connect = on_connect
    client.on_publish = on_publish
    client.on_disconnect = on_disconnect
    
    # Connect to broker
    try:
        logger.info(f"🔌 Connecting to MQTT broker {BROKER}:{PORT}...")
        client.connect(BROKER, PORT, 60)
        client.loop_start()
        time.sleep(2)  # Wait for connection
    except Exception as e:
        logger.error(f"❌ Failed to connect to broker: {e}")
        return
    
    # Execute selected test mode
    try:
        if choice == "1":
            test_single_publish(client)
        elif choice == "2":
            duration = input("Enter duration in minutes (default: 5): ").strip()
            duration = int(duration) if duration else 5
            test_continuous_publish(client, duration)
        elif choice == "3":
            count = input("Enter number of iterations (default: 100): ").strip()
            count = int(count) if count else 100
            test_stress_publish(client, count)
        elif choice == "4":
            test_anomaly_publish(client)
        elif choice == "5":
            logger.info("🚀 PRODUCTION MODE: Running forever (Ctrl+C to stop)")
            iteration = 0
            while True:
                iteration += 1
                logger.info(f"📊 Iteration #{iteration}")
                publish_all_sensors(client)
                time.sleep(PUBLISH_INTERVAL)
        else:
            logger.error("❌ Invalid choice")
    except KeyboardInterrupt:
        logger.info("\n⏹️ Stopped by user")
    except Exception as e:
        logger.error(f"❌ Error during execution: {e}")
    finally:
        # Cleanup
        logger.info("🧹 Cleaning up...")
        client.loop_stop()
        client.disconnect()
        logger.info("👋 Disconnected from broker")

if __name__ == "__main__":
    main()