import json
import logging

import paho.mqtt.client as mqtt

from envelope import build_envelope

logger = logging.getLogger(__name__)


class TinyGSMQTTClient:
    """
    Subscribes to the topics published by a TinyGS device and hands every
    message, wrapped in an envelope, to the server's /api/plugin-data/<type>.
    With a board bound to the instance it also forwards that board's reports.
    """

    def __init__(self, broker_url, broker_port, device_id, plugin_id, plugin_type,
                 api, username=None, password=None, qos=1,
                 topic_prefix="pluto", tracker=None, bridge=None):
        self.broker_url = broker_url
        self.broker_port = broker_port
        self.device_id = device_id
        self.plugin_id = plugin_id
        self.plugin_type = plugin_type
        # pluto_sdk.ApiClient: queues the request, so on_message never waits on HTTP.
        self.api = api
        # pluto_sdk.BoardBridge, or None when no board is bound to the instance.
        self.bridge = bridge
        self.qos = qos
        # The prefix is configurable on the station itself, so it is a setting
        # here too rather than a literal.
        self.tracking_topic = f"{topic_prefix}/{device_id}/tracking"
        self.rx_topic = f"{topic_prefix}/{device_id}/rx"
        # Turns the satellite named in each tracking message into a pass. None
        # keeps the plugin a pure relay of the board, which is what its tests build.
        self.tracker = tracker
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
        subscriptions = [(self.tracking_topic, self.qos), (self.rx_topic, self.qos)]
        if self.bridge is not None:
            subscriptions += self.bridge.subscriptions()
        client.subscribe(subscriptions)
        logger.info("Subscribed to %s", ", ".join(topic for topic, _ in subscriptions))

    def on_message(self, client, userdata, msg):
        if self.bridge is not None and self.bridge.handles(msg.topic):
            self.bridge.forward(msg.topic, msg.payload)
            return

        # Derived by comparing against the topics we subscribed to, not by
        # splitting msg.topic: the segment ends up in the request URL, so it
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
            self.api.send_data(message_type, envelope)
            logger.info(
                "[%s] device=%s format=%s bytes=%s id=%s queued for the server",
                message_type, self.device_id, envelope["payload_format"],
                len(msg.payload), envelope["message_id"],
            )
            logger.debug("envelope: %s", envelope)

            if message_type == "tracking" and self.tracker is not None:
                self._feed_tracker(msg.payload)
        except Exception:
            logger.exception("Failed to handle message from %s", msg.topic)

    def _feed_tracker(self, raw):
        # A payload that is not a JSON object still went to the server above:
        # the envelope knows how to carry text and binary. Only the tracker needs to
        # read it, and it has nothing to follow in one it cannot read.
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("tracking payload is not JSON, no pass to compute")
            return

        self.tracker.on_tracking(document)

    def publish_to_board(self, topic, payload):
        """Put one pointing batch or HOLD on the board's topic (coordinates-dto.md §2).

        Called from the dispatcher's timer thread; paho's publish is safe there.
        QoS 1, and never retained: a retained setpoint would be handed to the
        board on every reconnect, aiming it at an instant that has passed.
        """
        self.client.publish(topic, payload, qos=1, retain=False)

    def stop(self):
        """Leave the broker, which ends loop_forever and with it start()."""
        self.client.disconnect()
