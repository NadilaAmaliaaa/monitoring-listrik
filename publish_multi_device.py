import json
import time
import random
import paho.mqtt.client as mqtt
from datetime import datetime
import sys

# ==================== CONFIGURATION ====================
BROKER = "192.168.1.20" 
PORT = 1883
KEEPALIVE = 60

# Departments yang akan menerima data
DEPARTMENTS = [1, 3, 6]

# Base configuration untuk sensors (akan digunakan untuk semua department)
SENSOR_CONFIGS = {
    "PZEM1": {
        "phase": "R",
        "base_voltage": 220.0,
        "base_current": 5.0
    },
    "PZEM2": {
        "phase": "S",
        "base_voltage": 219.0,
        "base_current": 5.2
    },
    "PZEM3": {
        "phase": "T",
        "base_voltage": 221.0,
        "base_current": 4.8
    }
}

# Generate topics untuk semua department
SENSORS = {}
for dept_id in DEPARTMENTS:
    for sensor_name, config in SENSOR_CONFIGS.items():
        key = f"{sensor_name}_DEPT{dept_id}"
        SENSORS[key] = {
            "topic": f"sensor/department{dept_id}/{sensor_name}",
            "phase": config["phase"],
            "base_voltage": config["base_voltage"],
            "base_current": config["base_current"],
            "department": dept_id
        }

# Interval publish (detik)
PUBLISH_INTERVAL = 5

# Variasi data (untuk random)
VOLTAGE_VARIANCE = 3.0  # ±3V
CURRENT_VARIANCE = 0.5  # ±0.5A
FREQUENCY_VARIANCE = 0.2  # ±0.2Hz
PF_VARIANCE = 0.05  # ±0.05

# ==================== HELPER FUNCTIONS ====================
def generate_sensor_data(sensor_config):
    """
    Generate data sensor yang realistis
    
    Returns:
        dict: Data sensor dengan format PZEM004T
    """
    base_voltage = sensor_config["base_voltage"]
    base_current = sensor_config["base_current"]
    
    # Generate dengan variasi random
    voltage = base_voltage + random.uniform(-VOLTAGE_VARIANCE, VOLTAGE_VARIANCE)
    current = base_current + random.uniform(-CURRENT_VARIANCE, CURRENT_VARIANCE)
    frequency = 50.0 + random.uniform(-FREQUENCY_VARIANCE, FREQUENCY_VARIANCE)
    power_factor = 0.95 + random.uniform(-PF_VARIANCE, PF_VARIANCE)
    
    # Ensure bounds
    voltage = max(200.0, min(240.0, voltage))
    current = max(0.0, min(20.0, current))
    frequency = max(49.0, min(51.0, frequency))
    power_factor = max(0.0, min(1.0, power_factor))
    
    # Calculate power
    power = voltage * current * power_factor
    
    # Calculate energy (untuk 5 detik)
    energy_wh = power * (PUBLISH_INTERVAL / 3600.0)
    energy_kwh = energy_wh / 1000.0
    
    # Format data seperti PZEM004T
    data = {
        "tegangan": round(voltage, 2),
        "arus": round(current, 2),
        "daya": round(power, 2),
        "energi": round(energy_kwh, 6),
        "frekuensi": round(frequency, 2),
        "pf": round(power_factor, 3),
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    return data

def print_separator():
    """Print separator line"""
    print("=" * 80)

def print_header():
    """Print header"""
    print_separator()
    print(" " * 15 + "MQTT MULTI-DEPARTMENT SENSOR PUBLISHER")
    print_separator()
    print(f"Broker: {BROKER}:{PORT}")
    print(f"Publish Interval: {PUBLISH_INTERVAL} seconds")
    print(f"Departments: {DEPARTMENTS}")
    print(f"Total Sensors: {len(SENSORS)} ({len(SENSOR_CONFIGS)} sensors × {len(DEPARTMENTS)} departments)")
    print()
    
    # Group by department
    for dept_id in DEPARTMENTS:
        print(f"Department {dept_id}:")
        for sensor_name in SENSOR_CONFIGS.keys():
            key = f"{sensor_name}_DEPT{dept_id}"
            config = SENSORS[key]
            print(f"  • {sensor_name} (Phase {config['phase']}) → {config['topic']}")
        print()
    
    print_separator()
    print()

# ==================== MQTT CALLBACKS ====================
def on_connect(client, userdata, flags, rc):
    """Callback when connected to MQTT broker"""
    if rc == 0:
        print(f"✓ Connected to MQTT Broker at {BROKER}:{PORT}\n")
        print("Publishing data to all departments... (Press Ctrl+C to stop)\n")
    else:
        error_messages = {
            1: "Connection refused - incorrect protocol version",
            2: "Connection refused - invalid client identifier",
            3: "Connection refused - server unavailable",
            4: "Connection refused - bad username or password",
            5: "Connection refused - not authorized"
        }
        error_msg = error_messages.get(rc, f"Unknown error (code: {rc})")
        print(f"✗ Connection failed: {error_msg}")
        sys.exit(1)

def on_disconnect(client, userdata, rc):
    """Callback when disconnected from MQTT broker"""
    if rc != 0:
        print(f"\n✗ Unexpected disconnection (code: {rc})")
        print("Attempting to reconnect...")

def on_publish(client, userdata, mid):
    """Callback when message is published"""
    # Optional: uncomment untuk debug
    # print(f"  → Message {mid} published")
    pass

# ==================== MAIN PUBLISHER ====================
def publish_sensor_data(client):
    """
    Publish data dari semua sensor ke semua department
    """
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] Publishing data to all departments...")
    
    # Group by department for better display
    for dept_id in DEPARTMENTS:
        print(f"\n  Department {dept_id}:")
        
        for sensor_name in SENSOR_CONFIGS.keys():
            key = f"{sensor_name}_DEPT{dept_id}"
            sensor_config = SENSORS[key]
            
            # Generate data
            data = generate_sensor_data(sensor_config)
            
            # Convert to JSON
            payload = json.dumps(data)
            
            # Publish
            topic = sensor_config["topic"]
            result = client.publish(topic, payload, qos=0)
            
            # Print info
            phase = sensor_config["phase"]
            print(f"    Phase {phase} ({sensor_name}): "
                  f"V={data['tegangan']}V, "
                  f"I={data['arus']}A, "
                  f"P={data['daya']}W, "
                  f"PF={data['pf']}")
            
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                print(f"      ✗ Publish failed: {result.rc}")
    
    print()

def run_publisher():
    """
    Main function to run the publisher
    """
    # Print header
    print_header()
    
    # Create MQTT client
    client = mqtt.Client(client_id="multi_dept_publisher", clean_session=True)
    
    # Set callbacks
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_publish = on_publish
    
    # Connect to broker
    try:
        print(f"Connecting to {BROKER}:{PORT}...")
        client.connect(BROKER, PORT, KEEPALIVE)
        client.loop_start()
        
        # Wait for connection
        time.sleep(2)
        
        # Publish loop
        message_count = 0
        while True:
            publish_sensor_data(client)
            message_count += 1
            
            # Show statistics every 10 messages
            if message_count % 10 == 0:
                total_messages = message_count * len(SENSORS)
                print(f"--- Statistics: {message_count} cycles, "
                      f"{total_messages} total messages sent ---")
                print(f"    ({message_count * len(SENSOR_CONFIGS)} messages per department)\n")
            
            time.sleep(PUBLISH_INTERVAL)
    
    except KeyboardInterrupt:
        print("\n\nStopping publisher...")
        client.loop_stop()
        client.disconnect()
        print_separator()
        print(f"✓ Publisher stopped successfully")
        print(f"  Total cycles: {message_count}")
        print(f"  Total messages: {message_count * len(SENSORS)}")
        print(f"  Messages per department: {message_count * len(SENSOR_CONFIGS)}")
        print_separator()
        sys.exit(0)
    
    except Exception as e:
        print(f"\n✗ Error: {e}")
        client.loop_stop()
        client.disconnect()
        sys.exit(1)

# ==================== COMMAND LINE INTERFACE ====================
if __name__ == "__main__":
    print("\n")
    
    # Check for command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] in ["-h", "--help"]:
            print("Usage: python mqtt_multi_dept_publisher.py [options]")
            print("\nOptions:")
            print("  -h, --help     Show this help message")
            print("  -t, --test     Run single test publish")
            print("\nConfiguration:")
            print(f"  Broker: {BROKER}:{PORT}")
            print(f"  Interval: {PUBLISH_INTERVAL} seconds")
            print(f"  Departments: {DEPARTMENTS}")
            print(f"  Sensors per department: {len(SENSOR_CONFIGS)}")
            print(f"  Total sensors: {len(SENSORS)}")
            sys.exit(0)
        
        elif sys.argv[1] in ["-t", "--test"]:
            print("Running single test publish to all departments...\n")
            
            # Create client
            client = mqtt.Client(client_id="test_multi_dept_publisher")
            client.on_connect = on_connect
            
            # Connect
            try:
                client.connect(BROKER, PORT, KEEPALIVE)
                client.loop_start()
                time.sleep(2)
                
                # Publish once
                publish_sensor_data(client)
                
                print("✓ Test publish completed successfully")
                print(f"  Published to {len(DEPARTMENTS)} departments")
                print(f"  Total {len(SENSORS)} messages sent")
                
                # Cleanup
                time.sleep(1)
                client.loop_stop()
                client.disconnect()
                
            except Exception as e:
                print(f"✗ Test failed: {e}")
                sys.exit(1)
            
            sys.exit(0)
    
    # Run normal publisher
    run_publisher()