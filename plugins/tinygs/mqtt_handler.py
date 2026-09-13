import json
import logging

import paho.mqtt.client as mqtt

from envelope import build_envelope

logger = logging.getLogger(__name__)


class TinyGSMQTTClient:
    """
    Subscribes to the topics published by a TinyGS device and republishes every
    message as an envelope on the plugin's own data topic, where the central
    ingester picks it up and persists it.
    """

    def __init__(self, broker_url, broker_port, device_id, plugin_id, plugin_type,
                 publish_topic_base, username=None, password=None, qos=1):
        self.broker_url = broker_url
        self.broker_port = broker_port
        self.device_id = device_id
        self.plugin_id = plugin_id
        self.plugin_type = plugin_type
        self.publish_topic_base = publish_topic_base.rstrip("/")
        self.qos = qos
        self.tracking_topic = f"pluto/{device_id}/tracking"
        self.rx_topic = f"pluto/{device_id}/rx"
        # A stable client_id makes a duplicated container visible: the broker
        # kicks the other one out instead of silently doubling every message.
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"tinygs-{plugin_id}")

        if username and password:
            self.client.username_pw_set(username, password)

        # In paho 2.x an exception inside a callback propagates and kills loop_forever.
        self.client.suppress_exceptions = True
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

    def start(self):
        logger.info("Connecting to MQTT broker at %s:%s", self.broker_url, self.broker_port)
        self.client.connect(self.broker_url, self.broker_port, 60)
        self.client.loop_forever(retry_first_connection=True)

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            logger.error("Failed to connect to MQTT broker with reason code %s", reason_code)
            return

        logger.info("Connected to MQTT broker successfully.")
        # Subscribing here (and not before connecting) is what makes the
        # subscriptions come back on their own after a broker restart.
        client.subscribe([(self.tracking_topic, self.qos), (self.rx_topic, self.qos)])
        logger.info("Subscribed to %s and %s", self.tracking_topic, self.rx_topic)
        logger.info("Republishing to %s/{tracking,rx}", self.publish_topic_base)

    def on_message(self, client, userdata, msg):
        # Derived by comparing against the topics we subscribed to, not by
        # splitting msg.topic: the segment ends up in the outgoing topic, so it
        # must never carry anything the board chose.
        message_type = "tracking" if msg.topic == self.tracking_topic else "rx"

        try:
            envelope = build_envelope(
                plugin_id=self.plugin_id,
                plugin_type=self.plugin_type,
                device=self.device_id,
                message_type=message_type,
                source_topic=msg.topic,
                raw=msg.payload,
            )
            out_topic = f"{self.publish_topic_base}/{message_type}"
            result = client.publish(out_topic, json.dumps(envelope), qos=self.qos)
            logger.info(
                "[%s] device=%s -> %s format=%s bytes=%s id=%s mid=%s",
                message_type, self.device_id, out_topic, envelope["payload_format"],
                len(msg.payload), envelope["message_id"], result.mid,
            )
            logger.debug("envelope: %s", envelope)
        except Exception:
            logger.exception("Failed to republish message from %s", msg.topic)
