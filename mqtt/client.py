import json
import paho.mqtt.client as mqtt
from mqtt.realtime_store import update

TOPICS = {
    "sensor/department3/PZEM1": "R",
    "sensor/department3/PZEM2": "S",
    "sensor/department3/PZEM3": "T"
}

def on_message(client, userdata, msg):
    phase = TOPICS.get(msg.topic)

    if not phase:
        return

    payload = json.loads(msg.payload)

    update(phase, {
        "voltage": payload["voltage"],
        "current": payload["current"],
        "power": payload["power"],
        "energy": payload["energy"],
        "pf": payload["power_factor"],
        "frequency": payload["frequency"],
        "timestamp": payload["time"]
    })

def start():
    client = mqtt.Client()
    client.on_message = on_message
    client.connect("localhost", 1883)

    for topic in TOPICS:
        client.subscribe(topic)

    client.loop_start()
