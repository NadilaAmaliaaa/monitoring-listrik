import json
import time
import logging
from datetime import datetime, timezone
import paho.mqtt.client as mqtt
from config import Config
from mqtt.mqtt_data_handler import (
    handle_mqtt_sensor_message,
    AggregationBuffer,
    logger
)

# Import realtime_store
try:
    from mqtt.realtime_store import update as update_realtime
    REALTIME_STORE_AVAILABLE = True
    logger.info("✓ Realtime store detected - Running in HYBRID mode")
except ImportError:
    REALTIME_STORE_AVAILABLE = False
    logger.info("⚠ Realtime store not found - Running in DB-only mode")


# -------------------- MQTT CONFIGURATIONS --------------------
BROKER = Config.MQTT_BROKER
PORT = Config.MQTT_PORT
KEEPALIVE = Config.MQTT_KEEPALIVE
RECONNECT_DELAY_SEC = Config.MQTT_RECONNECT_DELAY_SEC
TOPIC_PATTERN = Config.MQTT_TOPIC_PATTERN

# Sensor to Phase mapping
SENSOR_PHASE_MAP = {
    "PZEM1": "R",
    "PZEM2": "S",
    "PZEM3": "T"
}


class HybridMQTTClient:
    """
    Hybrid MQTT Client that handles:
    1. Realtime store updates (for instant dashboard display)
    2. Database aggregation (for historical data)
    """
    
    def __init__(self, broker=BROKER, port=PORT):
        self.broker = broker
        self.port = port
        self.client = None
        self.connected = False
        self.scheduler = None
        
        # Statistics
        self.msg_count = 0
        self.error_count = 0
        self.last_message_time = None
        
        logger.info(f"Hybrid MQTT Client initialized for {broker}:{port}")
        
    def on_connect(self, client, userdata, flags, rc):
        """Callback when connected to MQTT broker"""
        if rc == 0:
            self.connected = True
            logger.info(f"✓ Connected to MQTT Broker at {self.broker}:{self.port}")
            
            # Subscribe to sensor topics
            client.subscribe(TOPIC_PATTERN, qos=0)
            logger.info(f"✓ Subscribed to topic: {TOPIC_PATTERN}")
            
            if REALTIME_STORE_AVAILABLE:
                logger.info("✓ Realtime store is ACTIVE")
            
        else:
            self.connected = False
            error_messages = {
                1: "Connection refused - incorrect protocol version",
                2: "Connection refused - invalid client identifier",
                3: "Connection refused - server unavailable",
                4: "Connection refused - bad username or password",
                5: "Connection refused - not authorized"
            }
            error_msg = error_messages.get(rc, f"Unknown error code: {rc}")
            logger.error(f"✗ MQTT Connection failed: {error_msg}")
            
            # Attempt reconnection
            time.sleep(RECONNECT_DELAY_SEC)
            try:
                client.reconnect()
            except Exception as e:
                logger.error(f"Reconnection failed: {e}")
    
    def on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from MQTT broker"""
        self.connected = False
        
        if rc != 0:
            logger.warning(f"✗ Unexpected disconnection (rc={rc})")
            
            # Attempt reconnection
            time.sleep(RECONNECT_DELAY_SEC)
            try:
                logger.info("Attempting to reconnect...")
                client.reconnect()
            except Exception as e:
                logger.error(f"Reconnection failed: {e}")
        else:
            logger.info("✓ Gracefully disconnected from MQTT broker")
    
    def on_message(self, client, userdata, msg):
        """Callback when message received from MQTT broker"""
        try:
            # Update statistics
            self.msg_count += 1
            self.last_message_time = datetime.now(timezone.utc)
            
            # Decode payload
            payload = msg.payload.decode('utf-8')
            data = json.loads(payload)
            
            logger.debug(f"📨 [{self.msg_count}] Received from {msg.topic}")
            
            # Process sensor data
            if msg.topic.startswith("sensor/"):
                
                # ========================================
                # PRIORITY 1: Update Realtime Store FIRST
                # (for instant dashboard display)
                # ========================================
                if REALTIME_STORE_AVAILABLE:
                    success = self._update_realtime_store(msg.topic, data)
                    if not success:
                        logger.warning(f"⚠ Realtime store update failed for {msg.topic}")
                
                # ========================================
                # PRIORITY 2: Add to Aggregation Buffer
                # (for database storage every 15s)
                # ========================================
                handle_mqtt_sensor_message(msg.topic, data)
                
            else:
                logger.debug(f"Ignoring unrecognized topic: {msg.topic}")
                
        except json.JSONDecodeError as e:
            self.error_count += 1
            logger.error(f"✗ Invalid JSON from {msg.topic}: {e}")
            logger.debug(f"Raw payload: {msg.payload}")
            
        except Exception as e:
            self.error_count += 1
            logger.error(f"✗ Error processing message from {msg.topic}: {e}", exc_info=True)
    
    def _update_realtime_store(self, topic: str, data: dict) -> bool:
        """
        Update realtime store for instant dashboard display
        
        Args:
            topic: MQTT topic (e.g., "sensor/data/PZEM1")
            data: Parsed JSON data from MQTT message
            
        Returns:
            bool: True if update successful, False otherwise
        """
        try:
            # ========================================
            # STEP 1: Parse and validate topic
            # ========================================
            parts = topic.split("/")
            
            if len(parts) != 3:
                logger.debug(f"Invalid topic format: {topic} (expected 3 parts, got {len(parts)})")
                return False
            
            building_code = parts[1]
            sensor_name = parts[2]
            phase = SENSOR_PHASE_MAP.get(sensor_name)
            
            if not phase:
                logger.warning(f"Unknown sensor name: {sensor_name} (not in {list(SENSOR_PHASE_MAP.keys())})")
                return False
            
            # ========================================
            # STEP 2: Map MQTT fields to realtime format
            # ========================================
            # Validate required fields exist
            required_fields = ["tegangan", "arus", "daya", "energi", "pf", "frekuensi"]
            missing_fields = [f for f in required_fields if f not in data]
            
            if missing_fields:
                logger.warning(f"Missing fields in data: {missing_fields}")
                # Continue anyway with 0 values for missing fields
            
            # Convert and map fields with explicit type conversion
            realtime_data = {
                "voltage": float(data.get("tegangan", 0)),
                "current": float(data.get("arus", 0)),
                "power": float(data.get("daya", 0)),
                "energy": float(data.get("energi", 0)),
                "pf": float(data.get("pf", 0)),
                "frequency": float(data.get("frekuensi", 0)),
                "timestamp": data.get("time", datetime.now(timezone.utc).isoformat())
            }
            
            # ========================================
            # STEP 3: Update realtime store
            # ========================================
            update_realtime(building_code, phase, realtime_data)
            
            # Log success with key metrics
            logger.info(
                f"✓ Realtime store updated: Phase {phase} → "
                f"V={realtime_data['voltage']:.1f}V, "
                f"I={realtime_data['current']:.2f}A, "
                f"P={realtime_data['power']:.1f}W"
            )
            
            return True
            
        except ValueError as e:
            logger.error(f"✗ Value conversion error in {topic}: {e}")
            logger.debug(f"Data received: {data}")
            return False
            
        except Exception as e:
            logger.error(f"✗ Error updating realtime store for {topic}: {e}", exc_info=True)
            return False

    def start(self, loop_forever=False):
        """
        Start the MQTT client
        
        Args:
            loop_forever: If True, runs in blocking mode. If False, runs in background.
            
        Returns:
            mqtt.Client: The MQTT client instance, or None if failed
        """
        try:
            # ========================================
            # Create MQTT client
            # ========================================
            self.client = mqtt.Client(
                client_id="",           # Auto-generate client ID
                clean_session=True      # Don't persist session
            )
            
            # Set callbacks
            self.client.on_connect = self.on_connect
            self.client.on_disconnect = self.on_disconnect
            self.client.on_message = self.on_message
            
            # ========================================
            # Connect to broker
            # ========================================
            logger.info(f"Connecting to MQTT broker at {self.broker}:{self.port}...")
            self.client.connect(self.broker, self.port, KEEPALIVE)
            
            # ========================================
            # Start aggregation buffer flush worker
            # ========================================
            logger.info("Starting aggregation buffer flush worker...")
            self.scheduler = AggregationBuffer.start_flush_worker()
            
            # ========================================
            # Start MQTT loop
            # ========================================
            if loop_forever:
                logger.info("Starting MQTT loop (blocking mode)...")
                self.client.loop_forever()
            else:
                logger.info("Starting MQTT loop (non-blocking mode)...")
                self.client.loop_start()
            
            # ========================================
            # Startup summary
            # ========================================
            logger.info("=" * 60)
            logger.info("✓ Hybrid MQTT Client started successfully")
            logger.info(f"  → Broker: {self.broker}:{self.port}")
            logger.info(f"  → Topic: {TOPIC_PATTERN}")
            
            if REALTIME_STORE_AVAILABLE:
                logger.info("  → Realtime store: ENABLED (instant updates)")
            else:
                logger.info("  → Realtime store: DISABLED")
                
            logger.info("  → Database storage: ENABLED (15s aggregation)")
            logger.info("=" * 60)
            
            return self.client
            
        except Exception as e:
            logger.error(f"✗ Failed to start MQTT client: {e}", exc_info=True)
            return None
    
    def stop(self):
        """Stop MQTT client and cleanup resources"""
        try:
            logger.info("Stopping MQTT client...")
            
            # Stop MQTT loop
            if self.client:
                self.client.loop_stop()
                self.client.disconnect()
                logger.info("✓ MQTT client stopped")
            
            # Stop scheduler
            if self.scheduler:
                logger.info("Stopping scheduler...")
                self.scheduler.shutdown()
                logger.info("✓ Scheduler stopped")
            
            # Print statistics
            logger.info("=" * 60)
            logger.info(f"Session Statistics:")
            logger.info(f"  → Messages processed: {self.msg_count}")
            logger.info(f"  → Errors encountered: {self.error_count}")
            if self.last_message_time:
                logger.info(f"  → Last message: {self.last_message_time.strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info("=" * 60)
                
        except Exception as e:
            logger.error(f"✗ Error stopping MQTT client: {e}")
    
    def get_stats(self):
        """Get client statistics"""
        return {
            "connected": self.connected,
            "messages_processed": self.msg_count,
            "errors": self.error_count,
            "last_message": self.last_message_time.isoformat() if self.last_message_time else None
        }


# -------------------- HELPER FUNCTIONS --------------------

def start_mqtt_hybrid(loop_forever=False):
    """
    Start hybrid MQTT client
    
    Args:
        loop_forever: If True, runs in blocking mode
        
    Returns:
        HybridMQTTClient: The client instance
    """
    client = HybridMQTTClient()
    client.start(loop_forever=loop_forever)
    return client


# Alias for backward compatibility
start_mqtt = start_mqtt_hybrid


# -------------------- MAIN EXECUTION --------------------

if __name__ == "__main__":
    """Standalone execution for testing"""
    
    print("\n" + "="*70)
    print("HYBRID MQTT CLIENT - DUAL STORAGE SYSTEM")
    print("="*70)
    print(f"Broker     : {BROKER}:{PORT}")
    print(f"Topics     : {TOPIC_PATTERN}")
    print(f"Realtime   : {'ENABLED' if REALTIME_STORE_AVAILABLE else 'DISABLED'}")
    print(f"Database   : ENABLED")
    print("="*70)
    
    # Display registered sensors
    try:
        from mqtt.mqtt_data_handler import get_buildings_with_sensors
        
        buildings = get_buildings_with_sensors()
        if buildings:
            print("\n📍 Registered Sensors:")
            for building_name, info in buildings.items():
                print(f"\n   {building_name} ({info['building_code']})")
                for sensor in info['sensors']:
                    phase = SENSOR_PHASE_MAP.get(sensor['sensor_name'], '?')
                    print(f"   • {sensor['sensor_name']:8s} → Phase {phase}")
        else:
            print("\n⚠ No sensors registered in database")
    except Exception as e:
        logger.warning(f"Could not load sensor info: {e}")
    
    # Start client
    print("\n" + "="*70)
    print("Starting hybrid MQTT client...")
    print("="*70 + "\n")
    
    client = start_mqtt_hybrid(loop_forever=False)
    
    if client:
        print("✓ Hybrid MQTT Client is running")
        print("\nFeatures:")
        print("  • Realtime updates: <1s latency")
        print("  • Database saves: Every 15s")
        print("  • Auto-reconnect: Enabled")
        print("\nPress Ctrl+C to stop...\n")
        
        try:
            # Keep running
            while True:
                time.sleep(1)
                
                # Optional: Print stats every 60 seconds
                if client.msg_count > 0 and client.msg_count % 60 == 0:
                    stats = client.get_stats()
                    logger.info(f"📊 Stats: {stats['messages_processed']} msgs, "
                              f"{stats['errors']} errors, "
                              f"Connected: {stats['connected']}")
                    
        except KeyboardInterrupt:
            print("\n\n" + "="*70)
            print("Shutting down...")
            print("="*70)
            client.stop()
            print("\n✓ Client stopped successfully\n")
            
    else:
        print("\n✗ Failed to start client")
        print("Check logs for details")
        exit(1)