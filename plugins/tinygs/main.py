import json
import logging
import os
import sys

from mqtt_handler import TinyGSMQTTClient
from tle import TleCache
from tracker import Tracker

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("tinygs_main")


def build_station_from_env():
    """The ground station the orchestrator injected, as a {lat, lon, alt} dict.

    Same precedence as file_tracker: STATION_COORDINATES first, the three loose
    variables as a fallback. The station_location the board sends in every
    tracking message is ignored on purpose — the one configured in PluTO is the
    authority, and it carries the altitude the board does not.
    """
    station_coordinates = os.environ.get("STATION_COORDINATES", "")
    if station_coordinates:
        try:
            parsed = json.loads(station_coordinates)
            if isinstance(parsed, dict):
                return {
                    "lat": float(parsed["lat"]),
                    "lon": float(parsed["lon"]),
                    "alt": float(parsed.get("alt", 0.0)),
                }
            if isinstance(parsed, list) and len(parsed) >= 3:
                return {"lat": float(parsed[0]), "lon": float(parsed[1]), "alt": float(parsed[2])}
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            logger.warning("Invalid STATION_COORDINATES value, falling back to STATION_LAT/LON/ALT")

    return {
        "lat": float(os.environ.get("STATION_LAT", 0.0)),
        "lon": float(os.environ.get("STATION_LON", 0.0)),
        "alt": float(os.environ.get("STATION_ALT", 0.0)),
    }


def env_number(name, default):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None


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
    topic_prefix = os.environ.get("TINYGS_TOPIC_PREFIX", "").strip() or "pluto"
    # Every plugin gets plugin/<uuid>/coordinates/raw from the orchestrator:
    # the math engine is always in the path, even for a pass that is already
    # in az/el.
    coordinates_topic = os.environ.get("MQTT_PUBLISH_TOPIC", "").strip()

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

    if not coordinates_topic:
        if not plugin_id:
            logger.error("Either PLUGIN_ID/INSTANCE_ID or MQTT_PUBLISH_TOPIC is required.")
            return 1
        coordinates_topic = f"plugin/{plugin_id}/coordinates/raw"

    try:
        min_elevation_deg = env_number("MIN_ELEVATION_DEG", 10.0)
        lookahead_minutes = env_number("LOOKAHEAD_MINUTES", 20.0)
        sample_seconds = env_number("SAMPLE_SECONDS", 1.0)
        tle_ttl_hours = env_number("TLE_TTL_HOURS", 12.0)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

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
            topic_prefix=topic_prefix,
        )
        tracker = Tracker(
            station=build_station_from_env(),
            cache=TleCache(ttl_seconds=tle_ttl_hours * 3600),
            publish=mqtt_client.publish_coordinates,
            topic=coordinates_topic,
            min_elevation_deg=min_elevation_deg,
            lookahead_minutes=lookahead_minutes,
            sample_seconds=sample_seconds,
        )
        mqtt_client.tracker = tracker
        tracker.start()
        logger.info(
            "Passes above %s deg starting within %s min go to %s",
            min_elevation_deg, lookahead_minutes, coordinates_topic,
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
