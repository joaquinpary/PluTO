import logging
import os

import uvicorn

from api import app
from mqtt_handler import CoordinateTransformMQTTClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("coord_transform_main")


def main():
    logger.info("Starting coordinates transformation engine...")
    broker_url = os.environ.get("MQTT_BROKER_URL", "mosquitto")
    broker_port = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
    broker_user = os.environ.get("MQTT_USERNAME", "pluto")
    broker_pass = os.environ.get("MQTT_PASSWORD", "change-me")
    http_port = int(os.environ.get("TRANSFORM_PORT", "8000"))

    # The MQTT path stays until every plugin calls POST /transform; both go
    # through the same transform_payload.
    mqtt_client = CoordinateTransformMQTTClient(
        broker_url=broker_url,
        broker_port=broker_port,
        username=broker_user,
        password=broker_pass
    )
    mqtt_client.start_in_background()
    try:
        # uvicorn handles SIGTERM itself and returns, so the broker is left cleanly.
        uvicorn.run(app, host="0.0.0.0", port=http_port, log_level="info")
    finally:
        logger.info("Shutting down transformation engine...")
        mqtt_client.stop()

if __name__ == "__main__":
    main()
