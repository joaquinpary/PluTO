import docker
import os
import logging

logger = logging.getLogger(__name__)

class PluginOrchestrator:
    """
    Manages the lifecycle of plugin containers
    communicating securely through the Docker Socket Proxy.
    """
    
    def __init__(self):
        docker_host = os.environ.get('DOCKER_HOST', 'tcp://dockerproxy:2375')
        try:
            self.client = docker.DockerClient(base_url=docker_host)
        except Exception as e:
            logger.error(f"Fatal error: Could not connect to Docker Proxy. {e}")

    def spawn_plugin(self, plugin_type, instance_id, **kwargs):
        """
        Spawns an isolated container for a specific plugin.
        
        Parameters:
        - plugin_type: 'tinygs' or 'file_tracker' (matches your directory tree)
        - instance_id: A unique identifier (e.g. database ID)
        - kwargs: Additional environment variables (e.g. FILE_PATH)
        """
        valid_plugins = ['tinygs', 'file_tracker']
        if plugin_type not in valid_plugins:
            return False, f"Error: Plugin '{plugin_type}' not supported."

        format_type = plugin_type.replace("_", "-")
        container_name = f"plugin-{format_type}-{instance_id}"
        
        image_name = f"pluto/plugin-{format_type}:latest" 

        # To define        
        mqtt_topic = f"ingesta/{plugin_type}/{instance_id}/posicion"

        environment = {
            "MQTT_BROKER_URL": os.environ.get("MQTT_BROKER", "mosquitto"),
            "MQTT_PUBLISH_TOPIC": mqtt_topic,
            "INSTANCE_ID": str(instance_id)
        }
        
        environment.update(kwargs)

        try:
            container = self.client.containers.run(
                image=image_name,
                name=container_name,
                environment=environment,
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
        format_type = plugin_type.replace("_", "-")
        container_name = f"plugin-{format_type}-{instance_id}"
        try:
            container = self.client.containers.get(container_name)
            container.stop(timeout=5)
            container.remove()
            logger.info(f"Success: {container_name} destroyed.")
            return True, "Plugin shut down correctly."
            
        except docker.errors.NotFound:
            return False, "The plugin was already shut down or does not exist."
        except docker.errors.APIError as e:
            logger.error(f"Error destroying {container_name}: {str(e)}")
            return False, f"Internal error: {str(e)}"