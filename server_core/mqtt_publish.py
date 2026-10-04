"""One-off publishes from the web process.

The admin cannot share the long-lived clients of mqtt_ingest and mqtt_dispatch,
which run in their own containers, so each publish opens its own short
connection. That is fine for something a person triggers by hand.
"""
import paho.mqtt.publish as publish
from django.conf import settings


def publish_retained(topic, payload):
    """Publish and keep the message on the broker for later subscribers.

    An empty payload clears whatever was retained on the topic.
    """
    config = settings.MQTT_CONFIG
    auth = None
    if config["USERNAME"]:
        auth = {"username": config["USERNAME"], "password": config["PASSWORD"]}

    publish.single(
        topic,
        payload=payload,
        qos=1,
        retain=True,
        hostname=config["HOST"],
        port=config["PORT"],
        auth=auth,
    )
