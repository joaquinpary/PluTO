import logging
import os
from mqtt_handler import CoordinateTransformMQTTClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("coord_transform_main")

def main():
    logger.info("Starting coordinates transformation engine...")
    broker_url = os.environ.get("MQTT_BROKER_URL", "mosquitto")
    broker_port = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
    
    mqtt_client = CoordinateTransformMQTTClient(broker_url=broker_url, broker_port=broker_port)
    try:
        mqtt_client.start()
    except KeyboardInterrupt:
        logger.info("Shutting down transformation engine...")

if __name__ == "__main__":
    main()
