import logging
import os
import sys

from mqtt_handler import TinyGSMQTTClient

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("tinygs_main")


def main():
    logger.info("Starting tinygs subscriber...")
    broker_url = os.environ.get("MQTT_BROKER_URL", "mosquitto")
    broker_port = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
    broker_user = os.environ.get("MQTT_USERNAME", "pluto")
    broker_pass = os.environ.get("MQTT_PASSWORD", "change-me")
    device_id = os.environ.get("TINYGS_DEVICE", "").strip()

    # INSTANCE_ID is already injected into every plugin by the orchestrator.
    plugin_id = (os.environ.get("PLUGIN_ID") or os.environ.get("INSTANCE_ID", "")).strip()
    plugin_type = os.environ.get("PLUGIN_TYPE", "tinygs")
    topic_base = os.environ.get("MQTT_DATA_TOPIC_BASE", "").strip()

    if not device_id:
        # Exiting instead of falling back to a wildcard: a misconfigured plugin
        # must fail visibly, not silently listen to every device on the bus.
        logger.error("TINYGS_DEVICE is required and was not provided.")
        return 1

    if not topic_base:
        if not plugin_id:
            logger.error("Either PLUGIN_ID/INSTANCE_ID or MQTT_DATA_TOPIC_BASE is required.")
            return 1
        topic_base = f"plugin/{plugin_id}/data"

    try:
        mqtt_client = TinyGSMQTTClient(
            broker_url=broker_url,
            broker_port=broker_port,
            device_id=device_id,
            plugin_id=plugin_id,
            plugin_type=plugin_type,
            publish_topic_base=topic_base,
            username=broker_user,
            password=broker_pass,
        )
        mqtt_client.start()
    except KeyboardInterrupt:
        logger.info("Shutting down tinygs subscriber...")
    except Exception as exc:
        logger.error("An error occurred: %s", exc, exc_info=True)
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
