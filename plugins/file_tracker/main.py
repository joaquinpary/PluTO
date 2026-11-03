import json
import logging
import os
import signal
import sys

from models import Station
from mqtt_handler import FileTrackerMQTTClient
from pluto_sdk import ConfigurationError, antenna_from_environment, from_environment

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

    instance_id = os.environ.get("INSTANCE_ID", "unknown")
    input_topic = os.environ.get("MQTT_INPUT_TOPIC", f"plugin/{instance_id}/input/file")

    station = build_station_from_env()

    try:
        # file_tracker produces no data of its own: the API forwards the reports
        # of the board bound to the instance, and records what is sent to it.
        api, bridge = from_environment()
    except ConfigurationError as exc:
        logger.error("%s", exc)
        return 1
    if bridge is not None:
        logger.info("Forwarding the reports of board %s", bridge.device_id)

    try:
        mqtt_client = FileTrackerMQTTClient(
            broker_url=broker_url,
            broker_port=broker_port,
            username=broker_user,
            password=broker_pass,
            input_topic=input_topic,
            station=station,
            bridge=bridge,
        )
        antenna = antenna_from_environment(api, mqtt_client.publish_to_board)
        mqtt_client.antenna = antenna
        if antenna is None:
            logger.info("No board bound to this instance: files are parsed but not pointed at")

        def shutdown(_signum, _frame):
            # docker stop sends SIGTERM. Holding the antenna before leaving the
            # broker is what makes stopping the plugin stop the file in progress.
            logger.info("Signal received, shutting down file tracker...")
            if antenna is not None:
                antenna.stop()
            mqtt_client.stop()

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)

        mqtt_client.start()
    except ConfigurationError as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:
        logger.error("An error occurred: %s", exc, exc_info=True)
        # A failure must not look like a clean exit, to Docker or to whoever
        # reads `docker ps -a`.
        return 1
    finally:
        # Gives the queue a moment to report the last orders, the HOLD among them.
        api.stop(timeout=3)

    return 0

if __name__ == "__main__":
    sys.exit(main())
