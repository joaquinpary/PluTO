"""Which boards the broker knows, read from their retained status.

Every board leaves device/<device_id>/status retained (its LWT, device-state.md),
so the broker doubles as the list of boards that have ever connected. A scan
opens a short-lived connection from the web process, collects those retained
messages and leaves: nothing listens for boards between scans, however many
plugins there are. It is triggered by hand (POST /api/boards/scan), the same
kind of one-off connection as mqtt_publish.py.
"""
import threading
import time

import paho.mqtt.client as mqtt
from django.conf import settings

from .device_state import DEVICE_STATUS_TOPIC, parse_device_topic


class BrokerUnavailable(Exception):
    """The broker could not be reached, or refused the connection."""


def record_status(boards, topic, payload, retain):
    """Add one message to boards ({device_id: payload}). True if it was a board's status.

    Only retained messages count: a live one arriving mid-scan is a status
    change, and the next scan reads it retained anyway.
    """
    if not retain:
        return False
    parsed = parse_device_topic(topic)
    if parsed is None or parsed[1] != 'status':
        return False
    boards[parsed[0]] = payload
    return True


def scan_boards(timeout=2.0, quiet=0.3):
    """Return {device_id: status payload} for every board with a retained status.

    MQTT has no marker for "that was the last retained message", so the scan
    ends once `quiet` seconds pass without one after the subscription is
    acknowledged; the broker sends them in a burst right after that. `timeout`
    caps the whole thing. Raises BrokerUnavailable.
    """
    config = settings.MQTT_CONFIG
    boards = {}
    lock = threading.Lock()
    subscribed = threading.Event()
    refused = []
    last_activity = [None]

    def on_connect(client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            refused.append(reason_code)
            subscribed.set()
            return
        client.subscribe(DEVICE_STATUS_TOPIC, qos=1)

    def on_subscribe(client, userdata, mid, reason_code_list, properties=None):
        with lock:
            last_activity[0] = time.monotonic()
        subscribed.set()

    def on_message(client, userdata, msg):
        with lock:
            if record_status(boards, msg.topic, msg.payload, msg.retain):
                last_activity[0] = time.monotonic()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if config['USERNAME'] and config['PASSWORD']:
        client.username_pw_set(config['USERNAME'], config['PASSWORD'])
    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message

    started = time.monotonic()
    try:
        client.connect(config['HOST'], config['PORT'], keepalive=10)
    except OSError as exc:
        raise BrokerUnavailable(f'Could not reach the broker at {config["HOST"]}:{config["PORT"]}: {exc}') from exc

    client.loop_start()
    try:
        if not subscribed.wait(timeout):
            raise BrokerUnavailable('The broker did not answer the subscription in time.')
        if refused:
            raise BrokerUnavailable(f'The broker refused the connection: {refused[0]}')

        while time.monotonic() - started < timeout:
            with lock:
                idle = time.monotonic() - last_activity[0]
            if idle > quiet:
                break
            time.sleep(0.02)
    finally:
        # Disconnect first, so the network loop still sends the DISCONNECT.
        client.disconnect()
        client.loop_stop()

    with lock:
        return dict(boards)
