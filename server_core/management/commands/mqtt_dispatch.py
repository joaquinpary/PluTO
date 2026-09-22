"""Bridges plugin/+/coordinates/polar to device/<device_id>/coordinates/polar.

The hop that was missing between a tracking plugin and the antenna. It listens
for az/el trajectories, cuts them where they leave the rotor's limits, plans the
overlapping batches with coord_dto and publishes each one at its own instant.

Runs as its own container from the server image, like mqtt_ingest and for the
same reason: loop_forever() under runserver would be duplicated by the
autoreloader. The wire format is docs/contracts/coordinates-dto.md.
"""
import logging
import os
import signal
import threading
import time

import paho.mqtt.client as mqtt
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import DatabaseError, close_old_connections

from server_core.coord_dto import encode_hold
from server_core.dispatch import (
    POLAR_TOPIC,
    merge_trajectory,
    parse_polar_payload,
    parse_polar_topic,
    plan_for_rotor,
    record_order,
    resolve_rotor,
)
from server_core.models import DispatchOrder
from server_core.mqtt_runtime import wait_for_migrations

logger = logging.getLogger(__name__)

DEFAULT_TOPICS = (POLAR_TOPIC,)


def now_ms():
    """The wall clock in epoch milliseconds, the one both ends share over NTP."""
    return int(time.time() * 1000)


class Schedule:
    """Everything pending for one rotor, and the single timer that drives it.

    One timer per rotor instead of one per batch: a ten minute pass plans around
    three hundred batches, and that many live threads is a lot of address space
    to reserve for something that is idle by definition. The timer re-arms itself
    after each message, computing the next delay from the absolute clock so a
    late wakeup never accumulates.
    """

    def __init__(self, rotor, plugin, trajectory, batches, hold_at_ms, reason):
        self.rotor = rotor
        self.plugin = plugin
        self.trajectory = trajectory
        self.batches = batches
        self.hold_at_ms = hold_at_ms
        self.reason = reason
        # Walks the batches and then stops on the HOLD, one past the last one.
        self.index = 0
        self.timer = None

    def next_due_ms(self):
        """When the next message is due, or None once the HOLD has gone out."""
        if self.index < len(self.batches):
            return self.batches[self.index].send_at_ms
        if self.index == len(self.batches):
            return self.hold_at_ms
        return None

    def cancel(self):
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None


class Command(BaseCommand):
    help = 'Publishes the pointing batches a rotor has to execute, from the plugins\' polar coordinates.'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = None
        self.topics = list(DEFAULT_TOPICS)
        self.qos = 1
        self.stats = {'dispatched': 0, 'held': 0, 'rejected': 0, 'failed': 0}
        # One schedule per rotor. The lock covers both the dict and the plan
        # inside each schedule, which the timer threads walk as they fire.
        self._lock = threading.Lock()
        self._schedules = {}

    def add_arguments(self, parser):
        parser.add_argument(
            '--topic',
            action='append',
            dest='topics',
            help='Topic filter to subscribe to; repeat it for several. Defaults to all of them.',
        )
        parser.add_argument('--qos', type=int, default=1, help='Subscription QoS.')
        parser.add_argument('--host', default=None, help='Overrides MQTT_HOST.')
        parser.add_argument('--port', type=int, default=None, help='Overrides MQTT_PORT.')
        parser.add_argument('--client-id', default='pluto-mqtt-dispatch')
        parser.add_argument('--log-level', default=os.environ.get('LOG_LEVEL', 'INFO').upper())

    def handle(self, *args, **options):
        # Django configures handlers for its own loggers only, so without this
        # every INFO line from this command would be silently dropped.
        logging.basicConfig(
            level=options['log_level'],
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        )

        self.topics = list(options['topics'] or DEFAULT_TOPICS)
        self.qos = options['qos']

        wait_for_migrations()

        host = options['host'] or settings.MQTT_CONFIG['HOST']
        port = options['port'] or settings.MQTT_CONFIG['PORT']
        username = settings.MQTT_CONFIG['USERNAME']
        password = settings.MQTT_CONFIG['PASSWORD']

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=options['client_id'])
        if username and password:
            client.username_pw_set(username, password)

        # A single bad trajectory must never take the dispatcher down.
        client.suppress_exceptions = True
        client.on_connect = self.on_connect
        client.on_disconnect = self.on_disconnect
        client.on_message = self.on_message
        client.reconnect_delay_set(min_delay=1, max_delay=30)

        self.client = client
        self._install_signal_handlers(client)

        logger.info('Connecting to MQTT broker at %s:%s', host, port)
        client.connect(host, port, 60)
        try:
            # depends_on does not wait for the broker to be ready.
            client.loop_forever(retry_first_connection=True)
        except KeyboardInterrupt:
            logger.info('Shutting down the dispatcher...')
            self._cancel_all()
            client.disconnect()

        logger.info('Final stats: %s', self.stats)

    def _install_signal_handlers(self, client):
        def shutdown(_signum, _frame):
            logger.info('Signal received, disconnecting from the broker...')
            # Before the disconnect, so no timer wakes up on a closed client.
            self._cancel_all()
            client.disconnect()

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            logger.error('Failed to connect to MQTT broker with reason code %s', reason_code)
            return

        logger.info('Connected to MQTT broker successfully.')
        # Subscribing here means the subscription comes back on its own after a
        # broker restart.
        client.subscribe([(topic, self.qos) for topic in self.topics])
        logger.info('Subscribed to %s with qos=%s', ', '.join(self.topics), self.qos)

    def on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            logger.warning('Disconnected from MQTT broker (reason code %s), reconnecting...', reason_code)

    def on_message(self, client, userdata, msg):
        try:
            plugin_uuid = parse_polar_topic(msg.topic)
            if plugin_uuid is None:
                self.stats['rejected'] += 1
                logger.warning('Ignoring message on unexpected topic %s', msg.topic)
                return

            incoming = parse_polar_payload(msg.payload)
            if incoming is None:
                self.stats['rejected'] += 1
                return

            # What Django does before every request: drop a connection that is
            # stale or died (PostgreSQL restarted), so the query opens a fresh one.
            close_old_connections()

            resolved = resolve_rotor(plugin_uuid)
            if resolved is None:
                self.stats['rejected'] += 1
                return

            plugin, rotor = resolved
            self._install(plugin, rotor, incoming)
        except DatabaseError as exc:
            self.stats['failed'] += 1
            logger.error('Could not plan the trajectory from %s: %s', msg.topic, exc)
        except Exception:
            self.stats['failed'] += 1
            logger.exception('Unexpected error handling message from %s', msg.topic)

    def _install(self, plugin, rotor, incoming):
        """Merge what arrived into what was pending and re-arm the rotor."""
        moment = now_ms()

        with self._lock:
            previous = self._schedules.pop(rotor.pk, None)
            if previous is not None:
                previous.cancel()

            pending = previous.trajectory if previous is not None else []
            # Points already in the past are dead weight, and dropping them is
            # what keeps the working set bounded when a plugin streams one point
            # at a time forever.
            trajectory = [
                point for point in merge_trajectory(pending, incoming) if point[0] > moment
            ]

            planned = plan_for_rotor(rotor, trajectory, moment)
            if planned is None:
                self.stats['rejected'] += 1
                return

            batches, hold_at_ms, reason = planned
            schedule = Schedule(rotor, plugin, trajectory, batches, hold_at_ms, reason)
            self._schedules[rotor.pk] = schedule

            logger.info(
                'Planned %s batch(es) for %s from %s, holding at %s (%s)',
                len(batches), rotor.device_id, plugin.name, hold_at_ms, reason,
            )
            self._arm(schedule)

    def _arm(self, schedule):
        """Arm the timer for the next message. Called holding the lock."""
        due_ms = schedule.next_due_ms()
        if due_ms is None:
            self._schedules.pop(schedule.rotor.pk, None)
            return

        # Recomputed from the wall clock on every re-arm, so lateness never
        # accumulates along the chain. A batch that is already due goes out now:
        # file_tracker stamps its points from now() when it parses the file, so
        # the first ones routinely arrive with no lead time left.
        delay = max(0.0, due_ms / 1000 - time.time())
        schedule.timer = threading.Timer(delay, self._fire, args=(schedule,))
        schedule.timer.daemon = True
        schedule.timer.start()

    def _fire(self, schedule):
        try:
            with self._lock:
                # A trajectory that arrived while this timer was waiting replaces
                # the whole schedule; this one is then a ghost and must not publish.
                if self._schedules.get(schedule.rotor.pk) is not schedule:
                    return

                self._publish(schedule)
                schedule.index += 1
                self._arm(schedule)
        except DatabaseError as exc:
            self.stats['failed'] += 1
            logger.error('Could not record the order for %s: %s', schedule.rotor.device_id, exc)
        except Exception:
            self.stats['failed'] += 1
            logger.exception('Unexpected error publishing for %s', schedule.rotor.device_id)

    def _publish(self, schedule):
        close_old_connections()

        # Taken at publish time, not planned: this is what measures the transport
        # latency against the board's clock (§3.3).
        t_sent_ms = now_ms()
        topic = f'device/{schedule.rotor.device_id}/coordinates/polar'

        if schedule.index < len(schedule.batches):
            batch = schedule.batches[schedule.index]
            payload = batch.encode(t_sent_ms)
            kind, t0_ms, points, reason = DispatchOrder.Kind.BATCH, batch.t0_ms, batch.points, ''
        else:
            payload = encode_hold(t_sent_ms)
            kind, t0_ms, points, reason = DispatchOrder.Kind.HOLD, t_sent_ms, (), schedule.reason

        # retain=False without exception (§2): a retained setpoint would be handed
        # to the board on every reconnect, aiming it at an instant that has passed.
        self.client.publish(topic, payload, qos=1, retain=False)
        record_order(schedule.rotor, schedule.plugin, kind, t0_ms, t_sent_ms, points, reason)

        if kind == DispatchOrder.Kind.HOLD:
            self.stats['held'] += 1
            logger.info('[HOLD] %s reason=%s', schedule.rotor.device_id, reason)
        else:
            self.stats['dispatched'] += 1
            logger.info(
                '[BATCH] %s points=%s t0_ms=%s bytes=%s',
                schedule.rotor.device_id, len(points), t0_ms, len(payload),
            )

    def _cancel_all(self):
        with self._lock:
            for schedule in self._schedules.values():
                schedule.cancel()
            self._schedules.clear()
