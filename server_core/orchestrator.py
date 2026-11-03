import docker
import os
import logging
import json

from django.conf import settings

from .plugin_handlers import PLUGIN_HANDLERS

logger = logging.getLogger(__name__)

# Every plugin container is named plugin-<type>-<uuid> (container_name).
PLUGIN_CONTAINER_PREFIX = "plugin-"

# PluTO's own compose services whose logs the front end shows.
LOG_SERVICES = ("server", "coord_transform")


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

    def container_name(self, plugin_type, instance_id):
        format_type = plugin_type.replace("_", "-")
        return f"{PLUGIN_CONTAINER_PREFIX}{format_type}-{instance_id}"

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
                # The context is plugins/ rather than the plugin's own
                # directory, so its Dockerfile can copy the shared pluto_sdk.
                self.client.images.build(
                    path=os.path.dirname(source_path),
                    dockerfile=os.path.join(plugin_type, "Dockerfile"),
                    tag=image_name,
                    rm=True,
                )
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

    def spawn_plugin(self, plugin_type, instance_id, station_coordinates, api_token=None, rotor_device_id=None, **kwargs):
        """
        Spawns an isolated container for a specific plugin.
        
        Parameters:
        - plugin_type: 'tinygs' or 'file_tracker' (matches your directory tree)
        - instance_id: A unique identifier (e.g. database ID)
        - api_token: the plain token the container sends to /api/ (see api_tokens.py)
        - rotor_device_id: device_id of the board bound to the instance, if any
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

        container_name = self.container_name(plugin_type, instance_id)
        image_ok, image_result = self._build_image_if_needed(plugin_type)
        if not image_ok:
            return False, image_result

        image_name = image_result

        # The same broker settings the server uses. Without the credentials a
        # plugin falls back to its built-in defaults, and the broker refuses
        # anonymous clients, so changing MQTT_PASSWORD silently cut them all off.
        mqtt_config = settings.MQTT_CONFIG
        environment = {
            "MQTT_BROKER_URL": mqtt_config["HOST"],
            "MQTT_BROKER_PORT": str(mqtt_config["PORT"]),
            "MQTT_USERNAME": mqtt_config["USERNAME"],
            "MQTT_PASSWORD": mqtt_config["PASSWORD"],
            "INSTANCE_ID": str(instance_id),
            "STATION_COORDINATES": json.dumps(normalized_station),
            "STATION_LAT": str(normalized_station["lat"]),
            "STATION_LON": str(normalized_station["lon"]),
            "STATION_ALT": str(normalized_station["alt"]),
            "PLUTO_API_URL": settings.PLUTO_API_URL,
            "PLUTO_TRANSFORM_URL": settings.PLUTO_TRANSFORM_URL,
        }
        if api_token:
            environment["PLUTO_API_TOKEN"] = api_token
        # Only a plugin with a board listens to one; without it the plugin
        # produces data and nothing else.
        if rotor_device_id:
            environment["ROTOR_DEVICE_ID"] = rotor_device_id

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
            logger.info(f"Success: {container_name} started")
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

        container_name = self.container_name(plugin_type, instance_id)
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

        container_name = self.container_name(plugin_type, instance_id)
        try:
            container = self.client.containers.get(container_name)
            return True, container.status
        except docker.errors.NotFound:
            return True, "not_found"
        except docker.errors.APIError as exc:
            logger.error(f"Error querying status for {container_name}: {exc}")
            return False, "unknown"

    def container_statuses(self):
        """The Docker status of every plugin container, by container name (KAN-50).

        One request for the whole list instead of one per instance. None when
        Docker cannot be asked, so a caller can tell "unknown" from "no container".
        """
        if self.client is None:
            return None
        try:
            # sparse: the list answer already carries names and states; without
            # it the SDK inspects every container, one request each.
            containers = self.client.containers.list(all=True, sparse=True)
        except docker.errors.APIError as exc:
            logger.error(f"Error listing the plugin containers: {exc}")
            return None

        statuses = {}
        for container in containers:
            for name in container.attrs.get("Names") or []:
                name = name.lstrip("/")
                if name.startswith(PLUGIN_CONTAINER_PREFIX):
                    statuses[name] = container.status
        return statuses

    def container_logs(self, plugin_type, instance_id, tail):
        """The last `tail` lines a plugin container logged, or None without a container."""
        if self.client is None:
            return None
        try:
            container = self.client.containers.get(self.container_name(plugin_type, instance_id))
        except docker.errors.NotFound:
            return None
        except docker.errors.APIError as exc:
            logger.error(f"Error looking up the container of {instance_id}: {exc}")
            return None
        return self._read_logs(container, tail)

    def service_logs(self, service, tail):
        """The last `tail` lines of one of PluTO's own services, or None.

        Found by the label compose puts on its containers. PluTO already
        assumes one stack per Docker host (pluto-network, the plugin container
        names), so the first match is the one.
        """
        if service not in LOG_SERVICES or self.client is None:
            return None
        try:
            containers = self.client.containers.list(all=True, filters={"label": [
                f"com.docker.compose.service={service}",
                # Not a `docker compose run` of the same service, e.g. the test suite.
                "com.docker.compose.oneoff=False",
            ]})
        except docker.errors.APIError as exc:
            logger.error(f"Error looking up the {service} container: {exc}")
            return None
        if not containers:
            return None
        return self._read_logs(containers[0], tail)

    def _read_logs(self, container, tail):
        try:
            raw = container.logs(tail=tail)
        except docker.errors.APIError as exc:
            logger.error(f"Error reading logs: {exc}")
            return None
        # A container may log anything; one byte that is not UTF-8 must not cost the page.
        return raw.decode("utf-8", errors="replace").splitlines()
