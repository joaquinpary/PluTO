import docker
import os
import logging
import json

from django.conf import settings

from .plugin_handlers import PLUGIN_HANDLERS

logger = logging.getLogger(__name__)


def _normalize_station_coordinates(station_coordinates):
    if isinstance(station_coordinates, dict):
        return {
            "lat": float(station_coordinates["lat"]),
            "lon": float(station_coordinates["lon"]),
            "alt": float(station_coordinates.get("alt", 0.0)),
        }

    if isinstance(station_coordinates, (list, tuple)) and len(station_coordinates) >= 3:
        return {
            "lat": float(station_coordinates[0]),
            "lon": float(station_coordinates[1]),
            "alt": float(station_coordinates[2]),
        }

    if isinstance(station_coordinates, str):
        try:
            parsed = json.loads(station_coordinates)
            return _normalize_station_coordinates(parsed)
        except (json.JSONDecodeError, TypeError, ValueError, KeyError):
            pass

    raise ValueError("station_coordinates must be a dict, a [lat, lon, alt] list, or a JSON string with that shape")

class PluginOrchestrator:
    """
    Manages the lifecycle of plugin containers
    communicating securely through the Docker Socket Proxy.
    """
    
    def __init__(self):
        docker_host = os.environ.get('DOCKER_HOST', 'tcp://dockerproxy:2375')
        self.client = None
        try:
            self.client = docker.DockerClient(base_url=docker_host)
            self.client.ping()
        except docker.errors.DockerException as e:
            self.client = None
            logger.error(f"Fatal error: Could not connect to Docker Proxy. {e}")

    def _container_name(self, plugin_type, instance_id):
        format_type = plugin_type.replace("_", "-")
        return f"plugin-{format_type}-{instance_id}"

    def _image_name(self, plugin_type):
        format_type = plugin_type.replace("_", "-")
        return f"pluto/plugin-{format_type}:latest"

    def _plugin_source_path(self, plugin_type):
        return os.path.join(settings.BASE_DIR, "plugins", plugin_type)

    def _build_image_if_needed(self, plugin_type):
        image_name = self._image_name(plugin_type)
        source_path = self._plugin_source_path(plugin_type)

        if not os.path.isdir(source_path):
            return False, f"Error: Plugin source directory '{source_path}' does not exist."

        try:
            self.client.images.get(image_name)
            return True, image_name
        except docker.errors.ImageNotFound:
            try:
                self.client.images.build(path=source_path, tag=image_name, rm=True)
                logger.info(f"Built Docker image '{image_name}' from '{source_path}'")
                return True, image_name
            except docker.errors.BuildError as exc:
                logger.error(f"Docker build failed for '{image_name}': {exc}")
                return False, f"Error building Docker image for '{plugin_type}': {exc}"
            except docker.errors.APIError as exc:
                logger.error(f"Docker API error while building '{image_name}': {exc}")
                return False, f"Docker API error while building image for '{plugin_type}': {exc}"
        except docker.errors.APIError as exc:
            logger.error(f"Docker API error while checking image '{image_name}': {exc}")
            return False, f"Docker API error while checking image for '{plugin_type}': {exc}"

    def spawn_plugin(self, plugin_type, instance_id, station_coordinates, **kwargs):
        """
        Spawns an isolated container for a specific plugin.
        
        Parameters:
        - plugin_type: 'tinygs' or 'file_tracker' (matches your directory tree)
        - instance_id: A unique identifier (e.g. database ID)
        - kwargs: Additional environment variables (e.g. FILE_PATH)
        """
        handler = PLUGIN_HANDLERS.get(plugin_type)
        if handler is None:
            return False, f"Error: Plugin '{plugin_type}' not supported."

        if self.client is None:
            return False, "Cannot connect to Docker Proxy."

        try:
            normalized_station = _normalize_station_coordinates(station_coordinates)
        except ValueError as exc:
            return False, f"Error: {exc}"

        container_name = self._container_name(plugin_type, instance_id)
        image_ok, image_result = self._build_image_if_needed(plugin_type)
        if not image_ok:
            return False, image_result

        image_name = image_result

        mqtt_topic = f"plugin/{instance_id}/coordinates/raw"

        environment = {
            "MQTT_BROKER_URL": os.environ.get("MQTT_BROKER", "mosquitto"),
            "MQTT_PUBLISH_TOPIC": mqtt_topic,
            "INSTANCE_ID": str(instance_id),
            "STATION_COORDINATES": json.dumps(normalized_station),
            "STATION_LAT": str(normalized_station["lat"]),
            "STATION_LON": str(normalized_station["lon"]),
            "STATION_ALT": str(normalized_station["alt"]),
        }

        error = handler.validate(kwargs)
        if error:
            return False, error

        environment.update(handler.get_environment({**kwargs, "plugin_id": str(instance_id)}))
        volumes = handler.get_volumes(kwargs)

        try:
            container = self.client.containers.run(
                image=image_name,
                name=container_name,
                environment=environment,
                volumes=volumes,
                network="pluto-network",
                detach=True,
                restart_policy={"Name": "on-failure", "MaximumRetryCount": 3} 
            )
            logger.info(f"Success: {container_name} started and publishing to {mqtt_topic}")
            return True, container.id
            
        except docker.errors.APIError as e:
            logger.error(f"Docker error when starting {container_name}: {str(e)}")
            return False, str(e)

    def kill_plugin(self, plugin_type, instance_id):
        """
        Shuts down and destroys the container of a plugin that is no longer needed.
        """
        if self.client is None:
            return False, "Cannot connect to Docker Proxy."

        container_name = self._container_name(plugin_type, instance_id)
        try:
            container = self.client.containers.get(container_name)
            container.stop(timeout=5)
            container.remove()
            logger.info(f"Success: {container_name} destroyed.")
            return True, "Plugin shut down correctly."
            
        except docker.errors.NotFound:
            return True, "The plugin was already shut down or does not exist."
        except docker.errors.APIError as e:
            logger.error(f"Error destroying {container_name}: {str(e)}")
            return False, f"Internal error: {str(e)}"

    def get_container_status(self, plugin_type, instance_id):
        if self.client is None:
            return False, "unknown"

        container_name = self._container_name(plugin_type, instance_id)
        try:
            container = self.client.containers.get(container_name)
            return True, container.status
        except docker.errors.NotFound:
            return True, "not_found"
        except docker.errors.APIError as exc:
            logger.error(f"Error querying status for {container_name}: {exc}")
            return False, "unknown"