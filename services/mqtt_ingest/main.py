import logging
import os

import mongoengine

from mqtt_handler import INGEST_TOPIC, IngestMQTTClient

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("mqtt_ingest_main")


def connect_to_mongo():
    host = os.environ.get("MONGO_HOST", "mongodb")
    port = int(os.environ.get("MONGO_PORT", "27017"))
    database = os.environ.get("MONGO_DB", "pluto")

    # The empty-string defaults matter: passing username='' to a server without
    # authentication still works, while passing a name the server does not know
    # fails on the first real operation, not on connect.
    mongoengine.connect(
        db=database,
        host=host,
        port=port,
        username=os.environ.get("MONGO_USERNAME", "") or None,
        password=os.environ.get("MONGO_PASSWORD", "") or None,
        authentication_source=os.environ.get("MONGO_AUTH_SOURCE", "admin") or None,
    )
    logger.info("MongoDB configured at %s:%s/%s", host, port, database)


def main():
    logger.info("Starting MQTT ingester...")
    broker_url = os.environ.get("MQTT_BROKER_URL", "mosquitto")
    broker_port = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
    broker_user = os.environ.get("MQTT_USERNAME", "pluto")
    broker_pass = os.environ.get("MQTT_PASSWORD", "change-me")
    topic = os.environ.get("MQTT_INGEST_TOPIC", INGEST_TOPIC)
    qos = int(os.environ.get("MQTT_INGEST_QOS", "1"))

    connect_to_mongo()

    mqtt_client = IngestMQTTClient(
        broker_url=broker_url,
        broker_port=broker_port,
        username=broker_user,
        password=broker_pass,
        topic=topic,
        qos=qos,
    )
    try:
        mqtt_client.start()
    except KeyboardInterrupt:
        logger.info("Shutting down MQTT ingester...")


if __name__ == "__main__":
    main()
