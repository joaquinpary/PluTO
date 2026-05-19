import logging
import time

import paho.mqtt.client as mqtt

from models import RawCoordinatesPayload

logger = logging.getLogger(__name__)


class FileTrackerMQTTClient:
    def __init__(self, broker_url, broker_port, topic, payload: RawCoordinatesPayload, username=None, password=None):
        self.broker_url = broker_url
        self.broker_port = broker_port
        self.topic = topic
        self.payload = payload
        self.client = mqtt.Client()

        if username and password:
            self.client.username_pw_set(username, password)

        self.client.on_connect = self.on_connect
        self.client.on_publish = self.on_publish

    def start(self):
        logger.info("Connecting to MQTT broker at %s:%s", self.broker_url, self.broker_port)
        self.client.connect(self.broker_url, self.broker_port, 60)
        self.client.loop_forever()

    def on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            logger.error("Failed to connect to MQTT broker with return code %s", rc)
            return

        logger.info("Connected to MQTT broker successfully.")
        payload_json = self.payload.model_dump_json()
        result = client.publish(self.topic, payload_json, qos=1)
        logger.info("Payload queued for publish to %s with mid=%s", self.topic, result.mid)

    def on_publish(self, client, userdata, mid):
        logger.info("Payload published successfully with mid=%s", mid)
        logger.info("Plugin task completed. Remaining connected and idle.")