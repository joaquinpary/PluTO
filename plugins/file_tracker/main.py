import logging
import os
import json

from models import Station
from mqtt_handler import FileTrackerMQTTClient
from parser import build_payload_from_file

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
    logger.info("Starting file tracker publisher...")
    broker_url = os.environ.get("MQTT_BROKER_URL", "mosquitto")
    broker_port = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
    broker_user = os.environ.get("MQTT_USERNAME", "pluto")
    broker_pass = os.environ.get("MQTT_PASSWORD", "change-me")
    publish_topic = os.environ.get("MQTT_PUBLISH_TOPIC", "plugin/unknown/coordinates/raw")

    station = build_station_from_env()

    coord_type = os.environ.get("COORD_TYPE", "ECEF")
    coord_format = os.environ.get("COORD_FORMAT", "CARTESIAN")
    file_path = os.environ.get("FILE_PATH", "")

    try:
        payload = build_payload_from_file(file_path, coord_type, coord_format, station)
        mqtt_client = FileTrackerMQTTClient(
            broker_url=broker_url,
            broker_port=broker_port,
            username=broker_user,
            password=broker_pass,
            topic=publish_topic,
            payload=payload,
        )
        mqtt_client.start()
    except KeyboardInterrupt:
        logger.info("Shutting down file tracker publisher...")
    except Exception as exc:
        logger.error("An error occurred: %s", exc, exc_info=True)

if __name__ == "__main__":
    main()
