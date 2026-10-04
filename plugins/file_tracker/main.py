import logging
import os
import json

from models import Station
from mqtt_handler import FileTrackerMQTTClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("file_tracker_main")


def build_station_from_env() -> Station:
    station_coordinates = os.environ.get("STATION_COORDINATES", "")
    if station_coordinates:
        try:
            parsed = json.loads(station_coordinates)
            if isinstance(parsed, dict):
                return Station(
                    lat=float(parsed["lat"]),
                    lon=float(parsed["lon"]),
                    alt=float(parsed.get("alt", 0.0)),
                )
            if isinstance(parsed, list) and len(parsed) >= 3:
                return Station(lat=float(parsed[0]), lon=float(parsed[1]), alt=float(parsed[2]))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            logger.warning("Invalid STATION_COORDINATES value, falling back to STATION_LAT/LON/ALT")

    return Station(
        lat=float(os.environ.get("STATION_LAT", 0.0)),
        lon=float(os.environ.get("STATION_LON", 0.0)),
        alt=float(os.environ.get("STATION_ALT", 0.0)),
    )

def main():
    logger.info("Starting file tracker...")
    broker_url = os.environ.get("MQTT_BROKER_URL", "mosquitto")
    broker_port = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
    broker_user = os.environ.get("MQTT_USERNAME", "pluto")
    broker_pass = os.environ.get("MQTT_PASSWORD", "change-me")
    publish_topic = os.environ.get("MQTT_PUBLISH_TOPIC", "plugin/unknown/coordinates/raw")

    instance_id = os.environ.get("INSTANCE_ID", "unknown")
    input_topic = os.environ.get("MQTT_INPUT_TOPIC", f"plugin/{instance_id}/input/file")

    station = build_station_from_env()

    try:
        mqtt_client = FileTrackerMQTTClient(
            broker_url=broker_url,
            broker_port=broker_port,
            username=broker_user,
            password=broker_pass,
            input_topic=input_topic,
            publish_topic=publish_topic,
            station=station,
        )
        mqtt_client.start()
    except KeyboardInterrupt:
        logger.info("Shutting down file tracker...")
    except Exception as exc:
        logger.error("An error occurred: %s", exc, exc_info=True)

if __name__ == "__main__":
    main()
