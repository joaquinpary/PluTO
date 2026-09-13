import json
import logging

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class TinyGSMQTTClient:
    """
    Subscribes to the topics published by a TinyGS device and logs whatever
    arrives. First iteration: no persistence, no transformation, no publishing.
    """

    def __init__(self, broker_url, broker_port, device_id, username=None, password=None):
        self.broker_url = broker_url
        self.broker_port = broker_port
        self.device_id = device_id
        self.tracking_topic = f"pluto/{device_id}/tracking"
        self.rx_topic = f"pluto/{device_id}/rx"
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        if username and password:
            self.client.username_pw_set(username, password)

        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def start(self):
        logger.info("Connecting to MQTT broker at %s:%s", self.broker_url, self.broker_port)
        self.client.connect(self.broker_url, self.broker_port, 60)
        self.client.loop_forever()

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            logger.error("Failed to connect to MQTT broker with reason code %s", reason_code)
            return

        logger.info("Connected to MQTT broker successfully.")
        # Subscribing here (and not before connecting) is what makes the
        # subscriptions come back on their own after a broker restart.
        client.subscribe([(self.tracking_topic, 0), (self.rx_topic, 0)])
        logger.info("Subscribed to %s and %s", self.tracking_topic, self.rx_topic)

    def on_message(self, client, userdata, msg):
        message_kind = msg.topic.rsplit("/", 1)[-1]
        logger.info("[%s] device=%s topic=%s\n%s", message_kind, self.device_id, msg.topic, self._format_payload(msg.payload))

    def _format_payload(self, payload: bytes) -> str:
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            return f"<raw {len(payload)} bytes> {payload!r}"

        try:
            return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            return text
