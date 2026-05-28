import logging
import json
import paho.mqtt.client as mqtt
from pydantic import ValidationError
from models import RawCoordinatesPayload, PolarCoordinatesPayload
from transformer import transform_coordinates

logger = logging.getLogger(__name__)

class CoordinateTransformMQTTClient:
    def __init__(self, broker_url="mosquitto", broker_port=1883, username=None, password=None):
        self.broker_url = broker_url
        self.broker_port = broker_port
        self.client = mqtt.Client()
        if username and password:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def start(self):
        logger.info(f"Connecting to MQTT broker at {self.broker_url}:{self.broker_port}")
        self.client.connect(self.broker_url, self.broker_port, 60)
        self.client.loop_forever()

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT broker successfully.")
            topic = "plugin/+/coordinates/raw"
            client.subscribe(topic)
            logger.info(f"Subscribed to topic: {topic}")
        else:
            logger.error(f"Failed to connect to MQTT broker with return code {rc}")

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        payload_str = msg.payload.decode('utf-8')
        logger.debug(f"Received message on topic {topic}")
        
        try:
            # Extraer instance_id del tópico (ej. plugin/<instance_id>/coordinates/raw)
            parts = topic.split('/')
            if len(parts) >= 4:
                plugin_type = parts[1] # En el nuevo formato parece que plugin_type e instance_id son el mismo segmento
                instance_id = parts[1]
            else:
                plugin_type = "unknown"
                instance_id = "unknown"
                logger.warning(f"Could not extract plugin_type and instance_id from topic {topic}")
                return
                
            # Validar y parsear JSON con Pydantic
            raw_payload = RawCoordinatesPayload.model_validate_json(payload_str)
            
            # Transformar
            polar_points = []
            for pt in raw_payload.coordinates:
                polar_pt = transform_coordinates(pt, raw_payload.station, raw_payload.type, raw_payload.coord_format)
                polar_points.append(polar_pt)
                
            # Construir payload de salida
            polar_payload = PolarCoordinatesPayload(
                station=raw_payload.station,
                coordinates=polar_points
            )
            
            # Publicar
            out_topic = f"plugin/{instance_id}/coordinates/polar"
            out_json = polar_payload.model_dump_json()
            client.publish(out_topic, out_json)
            logger.info(f"Successfully transformed and published {len(polar_points)} points to {out_topic}")
            
        except ValidationError as e:
            logger.error(f"Validation error for incoming payload on {topic}: {e}")
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON received on {topic}")
        except Exception as e:
            logger.error(f"Unexpected error processing message on {topic}: {e}")
