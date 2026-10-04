import logging
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from models import FileUpload, Station
from parser import build_payload_from_text

logger = logging.getLogger(__name__)


class FileTrackerMQTTClient:
    def __init__(self, broker_url, broker_port, input_topic, publish_topic, station: Station, username=None, password=None):
        self.broker_url = broker_url
        self.broker_port = broker_port
        self.input_topic = input_topic
        self.publish_topic = publish_topic
        self.station = station
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

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            logger.error("Failed to connect to MQTT broker: %s", reason_code)
            return

        # Subscribing here and not once in start(): a reconnection starts a
        # clean session, and the subscription has to be made again.
        client.subscribe(self.input_topic, qos=1)
        logger.info("Connected. Waiting for coordinates files on %s", self.input_topic)

    def on_message(self, client, userdata, msg):
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
            # Publishing it again would re-point the antenna mid-pass.
            logger.info("Ignoring %s, already published", upload.upload_id)
            return
        # Recorded before parsing, so a broken file is not retried every time
        # the connection drops.
        self.last_upload_id = upload.upload_id

        payload = build_payload_from_text(
            upload.content, upload.coord_type.value, upload.coord_format.value,
            self.station, datetime.now(timezone.utc),
        )
        result = client.publish(self.publish_topic, payload.model_dump_json(), qos=1)
        logger.info(
            "Published %s points from %s on %s (mid=%s)",
            len(payload.coordinates), upload.filename or upload.upload_id, self.publish_topic, result.mid,
        )
