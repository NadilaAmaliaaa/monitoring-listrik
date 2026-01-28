import json
import time
import logging
import paho.mqtt.client as mqtt
from config import Config, MQTT_CONFIG
from mqtt.mqtt_data_handler import (
    handle_mqtt_sensor_message,
    AggregationBuffer,
    get_buildings_with_sensors,
    logger
)

# -------------------- MQTT CONFIGURATIONS FROM ENV --------------------
BROKER = Config.MQTT_BROKER
PORT = Config.MQTT_PORT
KEEPALIVE = Config.MQTT_KEEPALIVE
RECONNECT_DELAY_SEC = Config.MQTT_RECONNECT_DELAY_SEC

# Topics dari .env
TOPIC_PATTERN = Config.MQTT_TOPIC_PATTERN
TOPIC_PREDICT = Config.MQTT_TOPIC_PREDICT
TOPIC_PREDICT_RESULT = Config.MQTT_TOPIC_PREDICT_RESULT


class MQTTClientManager:
    def __init__(self, broker=BROKER, port=PORT):
        self.broker = broker
        self.port = port
        self.client = None
        self.connected = False
        self.scheduler = None
        
        logger.info(f"MQTT Client Manager initialized for {broker}:{port}")
        
    def on_connect(self, client, userdata, flags, rc):
        """Callback ketika terhubung ke MQTT broker"""
        if rc == 0:
            self.connected = True
            logger.info(f"✓ Connected to MQTT Broker at {self.broker}:{self.port}")
            
            # Subscribe ke topic pattern dari .env
            client.subscribe(TOPIC_PATTERN, qos=0)
            logger.info(f"✓ Subscribed to topic: {TOPIC_PATTERN}")
            
            # Subscribe ke topic predict jika ada
            if TOPIC_PREDICT:
                client.subscribe(TOPIC_PREDICT, qos=0)
                logger.info(f"✓ Subscribed to topic: {TOPIC_PREDICT}")
            
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
            
            # Retry connection
            logger.info(f"Retrying connection in {RECONNECT_DELAY_SEC} seconds...")
            time.sleep(RECONNECT_DELAY_SEC)
            try:
                client.reconnect()
            except Exception as e:
                logger.error(f"Reconnection failed: {e}")
    
    def on_disconnect(self, client, userdata, rc):
        self.connected = False
        if rc != 0:
            logger.warning(f"✗ Unexpected disconnection from MQTT broker (rc={rc})")
            logger.info(f"Attempting to reconnect in {RECONNECT_DELAY_SEC} seconds...")
            time.sleep(RECONNECT_DELAY_SEC)
            try:
                client.reconnect()
            except Exception as e:
                logger.error(f"Reconnection failed: {e}")
        else:
            logger.info("✓ Cleanly disconnected from MQTT broker")
    
    def on_message(self, client, userdata, msg):
        try:
            # Decode payload
            payload = msg.payload.decode('utf-8')
            data = json.loads(payload)
            
            logger.debug(f"Received message from {msg.topic}: {payload[:100]}...")
            
            # Handle berdasarkan topic pattern
            if msg.topic.startswith("sensor/"):
                # Pesan dari sensor
                handle_mqtt_sensor_message(msg.topic, data)
                
            elif msg.topic == TOPIC_PREDICT:
                # Pesan untuk prediction
                logger.info(f"Prediction request received: {data}")
                # TODO: Implement prediction logic
                # Bisa publish hasil ke TOPIC_PREDICT_RESULT
                
            else:
                logger.debug(f"Unrecognized topic: {msg.topic}")
                
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from {msg.topic}: {e}")
        except Exception as e:
            logger.error(f"Error processing message from {msg.topic}: {e}")
    
    def on_subscribe(self, client, userdata, mid, granted_qos):
        logger.info(f"✓ Subscription confirmed (mid={mid}, qos={granted_qos})")
    
    def on_log(self, client, userdata, level, buf):
        # Uncomment untuk debug level MQTT
        # logger.debug(f"MQTT Log: {buf}")
        pass
    
    def start(self, loop_forever=False):
        try:
            # Buat client instance
            self.client = mqtt.Client(client_id="", clean_session=True)
            
            # Set callbacks
            self.client.on_connect = self.on_connect
            self.client.on_disconnect = self.on_disconnect
            self.client.on_message = self.on_message
            self.client.on_subscribe = self.on_subscribe
            # self.client.on_log = self.on_log  # Uncomment untuk debug
            
            # Connect ke broker
            logger.info(f"Connecting to MQTT broker at {self.broker}:{self.port}...")
            self.client.connect(self.broker, self.port, KEEPALIVE)
            
            # Start background scheduler untuk flush data
            logger.info("Starting aggregation buffer flush worker...")
            self.scheduler = AggregationBuffer.start_flush_worker()
            
            # Start loop
            if loop_forever:
                logger.info("Starting MQTT loop (blocking mode)...")
                self.client.loop_forever()
            else:
                logger.info("Starting MQTT loop (non-blocking mode)...")
                self.client.loop_start()
            
            return self.client
            
        except Exception as e:
            logger.error(f"✗ Failed to start MQTT client: {e}")
            return None
    
    def stop(self):
        """Stop MQTT client dan cleanup"""
        try:
            if self.client:
                logger.info("Stopping MQTT client...")
                self.client.loop_stop()
                self.client.disconnect()
                logger.info("✓ MQTT client stopped")
            
            if self.scheduler:
                logger.info("Stopping scheduler...")
                self.scheduler.shutdown()
                logger.info("✓ Scheduler stopped")
                
        except Exception as e:
            logger.error(f"Error stopping MQTT client: {e}")


# -------------------- STANDALONE FUNCTIONS --------------------

def start_mqtt_client(loop_forever=False):
    manager = MQTTClientManager()
    manager.start(loop_forever=loop_forever)
    return manager


def display_sensor_info():
    print("\n" + "="*60)
    print("SENSOR INFORMATION")
    print("="*60)
    
    buildings = get_buildings_with_sensors()
    
    if not buildings:
        print("No buildings/sensors found in database")
        return
    
    for building_name, info in buildings.items():
        print(f"\n📍 {building_name} (Code: {info['building_code']})")
        print(f"   Building ID: {info['building_id']}")
        
        if info['sensors']:
            print(f"   Sensors ({len(info['sensors'])}):")
            for sensor in info['sensors']:
                print(f"      • {sensor['sensor_name']} (ID: {sensor['sensor_id']})")
                print(f"        Topic: {sensor['topic']}")
        else:
            print("   No sensors registered")
    
    print("\n" + "="*60)


# -------------------- MAIN EXECUTION --------------------

if __name__ == "__main__":
    """
    Standalone execution untuk testing
    """
    print("\n" + "="*60)
    print("MQTT CLIENT STARTING")
    print("="*60)
    print(f"Broker: {BROKER}:{PORT}")
    print(f"Topics: {TOPIC_PATTERN}")
    print("="*60)
    
    # Display sensor info
    display_sensor_info()
    
    # Start MQTT client
    print("\nStarting MQTT client...")
    manager = start_mqtt_client(loop_forever=False)
    
    if manager and manager.client:
        print("\n✓ MQTT Client is running")
        print("Press Ctrl+C to stop...\n")
        
        try:
            # Keep running
            while True:
                time.sleep(1)
                
        except KeyboardInterrupt:
            print("\n\nStopping MQTT client...")
            manager.stop()
            print("✓ MQTT client stopped successfully")
    else:
        print("\n✗ Failed to start MQTT client")
        exit(1)