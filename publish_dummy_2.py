#!/usr/bin/env python3
"""
MQTT Sensor Dummy Publisher - ADVANCED VERSION
Berbagai mode simulasi untuk testing yang lebih realistis

Features:
- Normal mode: Data normal dengan variasi kecil
- Spike mode: Simulasi lonjakan arus/tegangan
- Fluctuation mode: Fluktuasi besar (simulasi unstable)
- Scenario mode: Pattern tertentu (pagi, siang, malam)

Usage:
    python mqtt_dummy_publisher_advanced.py [mode]
    
Modes:
    normal       - Mode normal (default)
    spike        - Simulasi spike random
    fluctuation  - Fluktuasi besar
    scenario     - Pattern berdasarkan waktu
    stress       - Stress test (publish cepat)
"""

import json
import time
import random
import paho.mqtt.client as mqtt
from datetime import datetime, timedelta
import sys
import argparse

# ==================== CONFIGURATION ====================
BROKER = "192.168.1.9"
PORT = 1883
KEEPALIVE = 60

SENSORS = {
    "PZEM1": {
        "topic": "sensor/department3/PZEM1",
        "phase": "R",
        "base_voltage": 220.0,
        "base_current": 5.0,
        "load_type": "constant"  # constant, variable, heavy
    },
    "PZEM2": {
        "topic": "sensor/department3/PZEM2",
        "phase": "S",
        "base_voltage": 219.0,
        "base_current": 5.2,
        "load_type": "variable"
    },
    "PZEM3": {
        "topic": "sensor/department3/PZEM3",
        "phase": "T",
        "base_voltage": 221.0,
        "base_current": 4.8,
        "load_type": "heavy"
    }
}

# ==================== MODE CONFIGURATIONS ====================

MODES = {
    "normal": {
        "interval": 5,
        "voltage_var": 3.0,
        "current_var": 0.5,
        "description": "Normal operation with small variations"
    },
    "spike": {
        "interval": 5,
        "voltage_var": 3.0,
        "current_var": 0.5,
        "spike_chance": 0.1,  # 10% chance of spike
        "spike_multiplier": 2.0,
        "description": "Random spikes in current/voltage"
    },
    "fluctuation": {
        "interval": 5,
        "voltage_var": 10.0,
        "current_var": 2.0,
        "description": "Large fluctuations (unstable power)"
    },
    "scenario": {
        "interval": 5,
        "description": "Pattern based on time of day"
    },
    "stress": {
        "interval": 1,  # 1 second interval
        "voltage_var": 3.0,
        "current_var": 0.5,
        "description": "Stress test - rapid publishing"
    }
}


# ==================== DATA GENERATORS ====================

class SensorDataGenerator:
    """Generate realistic sensor data based on mode"""
    
    def __init__(self, mode="normal"):
        self.mode = mode
        self.config = MODES.get(mode, MODES["normal"])
        self.spike_active = {}
        
    def generate_normal(self, sensor_config):
        """Normal mode: small variations"""
        base_v = sensor_config["base_voltage"]
        base_i = sensor_config["base_current"]
        
        voltage = base_v + random.uniform(-self.config["voltage_var"], 
                                         self.config["voltage_var"])
        current = base_i + random.uniform(-self.config["current_var"], 
                                         self.config["current_var"])
        
        return self._calculate_data(voltage, current)
    
    def generate_spike(self, sensor_config, sensor_name):
        """Spike mode: random spikes"""
        base_v = sensor_config["base_voltage"]
        base_i = sensor_config["base_current"]
        
        # Check if spike should occur
        if random.random() < self.config["spike_chance"]:
            self.spike_active[sensor_name] = 3  # Spike duration in cycles
            print(f"  ⚡ SPIKE DETECTED on {sensor_name}!")
        
        # Apply spike multiplier if active
        multiplier = 1.0
        if sensor_name in self.spike_active and self.spike_active[sensor_name] > 0:
            multiplier = self.config["spike_multiplier"]
            self.spike_active[sensor_name] -= 1
        
        voltage = (base_v + random.uniform(-self.config["voltage_var"], 
                                          self.config["voltage_var"])) * multiplier
        current = (base_i + random.uniform(-self.config["current_var"], 
                                          self.config["current_var"])) * multiplier
        
        return self._calculate_data(voltage, current)
    
    def generate_fluctuation(self, sensor_config):
        """Fluctuation mode: large variations"""
        base_v = sensor_config["base_voltage"]
        base_i = sensor_config["base_current"]
        
        voltage = base_v + random.uniform(-self.config["voltage_var"], 
                                         self.config["voltage_var"])
        current = base_i + random.uniform(-self.config["current_var"], 
                                         self.config["current_var"])
        
        return self._calculate_data(voltage, current)
    
    def generate_scenario(self, sensor_config):
        """Scenario mode: pattern based on time"""
        hour = datetime.now().hour
        
        # Load patterns by time of day
        if 6 <= hour < 9:  # Pagi: beban naik
            load_factor = 0.7 + (hour - 6) * 0.1
        elif 9 <= hour < 17:  # Siang: beban penuh
            load_factor = 1.0 + random.uniform(-0.1, 0.1)
        elif 17 <= hour < 22:  # Sore-malam: beban turun
            load_factor = 1.0 - (hour - 17) * 0.1
        else:  # Malam-dini hari: beban minimal
            load_factor = 0.3 + random.uniform(-0.1, 0.1)
        
        base_v = sensor_config["base_voltage"]
        base_i = sensor_config["base_current"]
        
        voltage = base_v + random.uniform(-3.0, 3.0)
        current = (base_i * load_factor) + random.uniform(-0.3, 0.3)
        
        return self._calculate_data(voltage, current)
    
    def _calculate_data(self, voltage, current):
        """Calculate derived values from voltage and current"""
        # Bounds
        voltage = max(200.0, min(240.0, voltage))
        current = max(0.0, min(20.0, current))
        
        # Power factor (slight variation)
        power_factor = 0.95 + random.uniform(-0.05, 0.05)
        power_factor = max(0.80, min(1.0, power_factor))
        
        # Frequency (slight variation)
        frequency = 50.0 + random.uniform(-0.2, 0.2)
        frequency = max(49.5, min(50.5, frequency))
        
        # Calculate power
        power = voltage * current * power_factor
        
        # Calculate energy (for interval)
        interval = self.config["interval"]
        energy_wh = power * (interval / 3600.0)
        energy_kwh = energy_wh / 1000.0
        
        return {
            "tegangan": round(voltage, 2),
            "arus": round(current, 2),
            "daya": round(power, 2),
            "energi": round(energy_kwh, 6),
            "frekuensi": round(frequency, 2),
            "pf": round(power_factor, 3),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    
    def generate(self, sensor_config, sensor_name):
        """Generate data based on current mode"""
        if self.mode == "spike":
            return self.generate_spike(sensor_config, sensor_name)
        elif self.mode == "fluctuation":
            return self.generate_fluctuation(sensor_config)
        elif self.mode == "scenario":
            return self.generate_scenario(sensor_config)
        else:  # normal, stress, or default
            return self.generate_normal(sensor_config)


# ==================== MQTT PUBLISHER ====================

class DummyPublisher:
    """MQTT Publisher with multiple modes"""
    
    def __init__(self, mode="normal"):
        self.mode = mode
        self.config = MODES.get(mode, MODES["normal"])
        self.generator = SensorDataGenerator(mode)
        self.client = None
        self.connected = False
        self.message_count = 0
        
    def on_connect(self, client, userdata, flags, rc):
        """Callback on connection"""
        if rc == 0:
            self.connected = True
            print(f"✓ Connected to {BROKER}:{PORT}\n")
            print(f"Mode: {self.mode.upper()}")
            print(f"Description: {self.config['description']}")
            print(f"Publish Interval: {self.config['interval']} seconds\n")
            print("Publishing... (Press Ctrl+C to stop)\n")
        else:
            print(f"✗ Connection failed (code: {rc})")
            sys.exit(1)
    
    def on_disconnect(self, client, userdata, rc):
        """Callback on disconnection"""
        self.connected = False
        if rc != 0:
            print(f"\n✗ Unexpected disconnection (code: {rc})")
    
    def publish_cycle(self):
        """Publish data from all sensors"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] Cycle #{self.message_count + 1}")
        
        for sensor_name, sensor_config in SENSORS.items():
            # Generate data
            data = self.generator.generate(sensor_config, sensor_name)
            
            # Convert to JSON
            payload = json.dumps(data)
            
            # Publish
            topic = sensor_config["topic"]
            result = self.client.publish(topic, payload, qos=0)
            
            # Print
            phase = sensor_config["phase"]
            status = "✓" if result.rc == mqtt.MQTT_ERR_SUCCESS else "✗"
            print(f"  {status} Phase {phase}: "
                  f"V={data['tegangan']}V, "
                  f"I={data['arus']}A, "
                  f"P={data['daya']}W")
        
        self.message_count += 1
        print()
    
    def run(self):
        """Main run loop"""
        # Print header
        self._print_header()
        
        # Create client
        self.client = mqtt.Client(client_id=f"dummy_pub_{self.mode}")
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        
        try:
            # Connect
            print(f"Connecting to {BROKER}:{PORT}...")
            self.client.connect(BROKER, PORT, KEEPALIVE)
            self.client.loop_start()
            
            # Wait for connection
            time.sleep(2)
            
            if not self.connected:
                raise Exception("Failed to connect")
            
            # Publish loop
            while True:
                self.publish_cycle()
                
                # Statistics every 12 cycles (1 minute for 5s interval)
                if self.message_count % 12 == 0:
                    self._print_statistics()
                
                time.sleep(self.config["interval"])
        
        except KeyboardInterrupt:
            self._stop()
        except Exception as e:
            print(f"\n✗ Error: {e}")
            self._stop()
            sys.exit(1)
    
    def _print_header(self):
        """Print header"""
        print("=" * 80)
        print(" " * 15 + "MQTT SENSOR DUMMY PUBLISHER - ADVANCED")
        print("=" * 80)
        print(f"Broker: {BROKER}:{PORT}")
        print(f"Sensors: {len(SENSORS)}")
        for name, cfg in SENSORS.items():
            print(f"  • {name} (Phase {cfg['phase']})")
        print("=" * 80)
        print()
    
    def _print_statistics(self):
        """Print statistics"""
        total_messages = self.message_count * len(SENSORS)
        runtime_min = (self.message_count * self.config["interval"]) / 60
        print(f"--- STATS: {self.message_count} cycles, "
              f"{total_messages} messages, "
              f"{runtime_min:.1f} min runtime ---\n")
    
    def _stop(self):
        """Stop publisher"""
        print("\n\nStopping...")
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
        
        print("=" * 80)
        print("✓ Publisher stopped")
        print(f"  Mode: {self.mode}")
        print(f"  Total cycles: {self.message_count}")
        print(f"  Total messages: {self.message_count * len(SENSORS)}")
        print("=" * 80)


# ==================== COMMAND LINE INTERFACE ====================

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="MQTT Sensor Dummy Publisher - Advanced",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available Modes:
  normal       - Normal operation (default)
  spike        - Random spikes simulation
  fluctuation  - Large fluctuations
  scenario     - Time-based load pattern
  stress       - Rapid publishing (1s interval)

Examples:
  python mqtt_dummy_publisher_advanced.py
  python mqtt_dummy_publisher_advanced.py --mode spike
  python mqtt_dummy_publisher_advanced.py -m scenario
        """
    )
    
    parser.add_argument(
        "-m", "--mode",
        choices=MODES.keys(),
        default="normal",
        help="Publishing mode (default: normal)"
    )
    
    parser.add_argument(
        "-l", "--list",
        action="store_true",
        help="List available modes"
    )
    
    args = parser.parse_args()
    
    # List modes
    if args.list:
        print("\nAvailable Modes:")
        print("=" * 60)
        for mode, config in MODES.items():
            print(f"\n{mode.upper()}")
            print(f"  Description: {config['description']}")
            print(f"  Interval: {config['interval']}s")
        print("\n" + "=" * 60)
        return
    
    # Run publisher
    publisher = DummyPublisher(mode=args.mode)
    publisher.run()


if __name__ == "__main__":
    main()