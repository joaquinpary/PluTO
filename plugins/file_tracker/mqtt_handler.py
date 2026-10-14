import logging
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from models import FileUpload, Station
from parser import build_payload_from_text

logger = logging.getLogger(__name__)


class FileTrackerMQTTClient:
    def __init__(self, broker_url, broker_port, input_topic, station: Station,
                 username=None, password=None, bridge=None, antenna=None):
        self.broker_url = broker_url
        self.broker_port = broker_port
        self.input_topic = input_topic
        self.station = station
        # pluto_sdk.BoardBridge and pluto_sdk.Antenna, or None when no board is
        # bound to the instance.
        self.bridge = bridge
        self.antenna = antenna
        self.last_upload_id = None
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        if username and password:
            self.client.username_pw_set(username, password)

        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def start(self):
        logger.info("Connecting to MQTT broker at %s:%s", self.broker_url, self.broker_port)
        self.client.connect(self.broker_url, self.broker_port, 60)
        self.client.loop_forever()

    def stop(self):
        """Leave the broker, which ends loop_forever and with it start()."""
        self.client.disconnect()

    def publish_to_board(self, topic, payload):
        """Put one pointing batch or HOLD on the board's topic (coordinates-dto.md §2).

        Called from the dispatcher's timer thread; paho's publish is safe there.
        QoS 1, and never retained: a retained setpoint would be handed to the
        board on every reconnect, aiming it at an instant that has passed.
        """
        self.client.publish(topic, payload, qos=1, retain=False)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            logger.error("Failed to connect to MQTT broker: %s", reason_code)
            return

        # Subscribing here and not once in start(): a reconnection starts a
        # clean session, and the subscription has to be made again.
        subscriptions = [(self.input_topic, 1)]
        if self.bridge is not None:
            subscriptions += self.bridge.subscriptions()
        client.subscribe(subscriptions)
        logger.info("Connected. Waiting for coordinates files on %s", self.input_topic)

    def on_message(self, client, userdata, msg):
        if self.bridge is not None and self.bridge.handles(msg.topic):
            self.bridge.forward(msg.topic, msg.payload)
            return

        # A broad catch: a bad file is the uploader's mistake and must not take
        # the plugin down; the next upload has to find it listening.
        try:
            self.handle_upload(client, msg.payload)
        except Exception as exc:
            logger.error("Discarded the file on %s: %s", msg.topic, exc)

    def handle_upload(self, client, raw):
        if not raw:
            # The server cleared the retained file.
            return

        upload = FileUpload.model_validate_json(raw)
        if upload.upload_id == self.last_upload_id:
            # The broker hands the retained file back on every reconnection.
            # Pointing at it again would restart the antenna mid-pass.
            logger.info("Ignoring %s, already sent to the antenna", upload.upload_id)
            return
        # Recorded before parsing, so a broken file is not retried every time
        # the connection drops.
        self.last_upload_id = upload.upload_id

        payload = build_payload_from_text(
            upload.content, upload.coord_type.value, upload.coord_format.value,
            self.station, datetime.now(timezone.utc),
        )
        if self.antenna is None:
            # Parsed anyway, so a broken file still shows up in the log.
            logger.warning(
                "No board bound to this instance: %s points from %s parsed but not pointed at",
                len(payload.coordinates), upload.filename or upload.upload_id,
            )
            return

        # The antenna transforms, plans and publishes on its own thread: this
        # is paho's network thread and must not wait on HTTP.
        self.antenna.submit(payload.model_dump(mode="json"))
        logger.info(
            "Sent %s points from %s to the antenna",
            len(payload.coordinates), upload.filename or upload.upload_id,
        )
