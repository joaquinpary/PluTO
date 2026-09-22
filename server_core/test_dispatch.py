import json
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import OperationalError
from django.db.models import ProtectedError
from django.test import SimpleTestCase, TestCase, override_settings

from .dispatch import (
    HOLD_GRACE_MS,
    POLAR_TOPIC,
    merge_trajectory,
    parse_polar_payload,
    parse_polar_topic,
    plan_for_rotor,
    record_order,
)
from .management.commands.mqtt_dispatch import Command
from .models import DispatchOrder, PluginInstance, Rotor

LOGGER = 'server_core.dispatch'
MODULE = 'server_core.management.commands.mqtt_dispatch'

DEVICE_ID = 'a1b2c3d4e5f6'

# A round instant to hang the fake clock on: 2026-09-18T20:30:00Z.
NOW_MS = 1789763400000

UNSET = object()


def at(offset_ms):
    return NOW_MS + offset_ms


def polar_payload(points):
    """What coord_transform publishes: a station plus timestamped az/el points."""
    document = {
        'station': {'lat': -31.44, 'lon': -64.19, 'alt': 470.0},
        'coordinates': [
            {
                'timestamp': datetime.fromtimestamp(t_ms / 1000, timezone.utc).isoformat(),
                'az': az_deg,
                'el': el_deg,
                'range': 1187.4,
            }
            for t_ms, az_deg, el_deg in points
        ],
    }
    return json.dumps(document).encode('utf-8')


def rising_pass(count=6, first_offset_ms=3000):
    """A trajectory climbing away from the horizon, one point per second."""
    return [
        (at(first_offset_ms + 1000 * index), 120.0 + index, 20.0 + 5 * index)
        for index in range(count)
    ]


class ParsePolarTopicTests(SimpleTestCase):
    def test_parses_valid_polar_topic(self):
        self.assertEqual(parse_polar_topic('plugin/3f2a-uuid/coordinates/polar'), '3f2a-uuid')

    def test_rejects_anything_else(self):
        for topic in (
            'plugin/3f2a-uuid/coordinates/raw',
            'plugin/3f2a-uuid/coordinates',
            'plugin/3f2a-uuid/coordinates/polar/extra',
            'plugin/3f2a-uuid/data/tracking',
            'device/a1b2c3d4e5f6/coordinates/polar',
            'plugin//coordinates/polar',
        ):
            with self.subTest(topic=topic):
                self.assertIsNone(parse_polar_topic(topic))


class ParsePolarPayloadTests(SimpleTestCase):
    def test_reads_what_coord_transform_publishes(self):
        trajectory = parse_polar_payload(polar_payload([(at(1000), 123.45, 45.0), (at(2000), 124.0, 45.3)]))

        self.assertEqual(trajectory, [(at(1000), 123.45, 45.0), (at(2000), 124.0, 45.3)])

    def test_points_come_back_in_time_order(self):
        trajectory = parse_polar_payload(polar_payload([(at(2000), 124.0, 45.3), (at(1000), 123.45, 45.0)]))

        self.assertEqual([point[0] for point in trajectory], [at(1000), at(2000)])

    def test_two_points_on_the_same_instant_collapse_into_the_last(self):
        trajectory = parse_polar_payload(polar_payload([(at(1000), 123.45, 45.0), (at(1000), 200.0, 10.0)]))

        self.assertEqual(trajectory, [(at(1000), 200.0, 10.0)])

    def test_timestamp_without_offset_is_taken_as_utc(self):
        document = {'station': {}, 'coordinates': [{'timestamp': '2026-09-18T20:30:00', 'az': 10.0, 'el': 20.0}]}

        trajectory = parse_polar_payload(json.dumps(document).encode())

        self.assertEqual(trajectory[0][0], NOW_MS)

    def test_unusable_points_are_skipped(self):
        document = {
            'station': {},
            'coordinates': [
                {'timestamp': 'not-a-date', 'az': 10.0, 'el': 20.0},
                {'timestamp': '2026-09-18T20:30:01+00:00', 'az': True, 'el': 20.0},
                {'timestamp': '2026-09-18T20:30:02+00:00', 'az': 10.0, 'el': None},
                {'timestamp': '2026-09-18T20:30:03+00:00', 'az': 10.0, 'el': 20.0},
                'not a point',
            ],
        }

        trajectory = parse_polar_payload(json.dumps(document).encode())

        self.assertEqual(trajectory, [(at(3000), 10.0, 20.0)])

    def test_returns_none_when_nothing_is_usable(self):
        for payload in (
            b'{"roto',
            b'\xff\xfe',
            b'[1, 2]',
            b'{"station": {}}',
            b'{"station": {}, "coordinates": []}',
            json.dumps({'coordinates': [{'timestamp': 'x', 'az': 1, 'el': 2}]}).encode(),
        ):
            with self.subTest(payload=payload):
                with self.assertLogs(LOGGER, level='WARNING'):
                    self.assertIsNone(parse_polar_payload(payload))


class RotorLimitsTests(SimpleTestCase):
    def rotor(self, **overrides):
        return Rotor(device_id=DEVICE_ID, **overrides)

    def test_without_a_window_every_azimuth_is_allowed(self):
        rotor = self.rotor()

        for az_deg in (0.0, 180.0, 359.9):
            self.assertTrue(rotor.azimuth_in_window(az_deg))

    def test_plain_window_is_a_closed_interval(self):
        rotor = self.rotor(min_azimuth_deg=90.0, max_azimuth_deg=180.0)

        self.assertTrue(rotor.azimuth_in_window(90.0))
        self.assertTrue(rotor.azimuth_in_window(180.0))
        self.assertFalse(rotor.azimuth_in_window(89.9))
        self.assertFalse(rotor.azimuth_in_window(180.1))

    def test_window_below_its_start_wraps_through_north(self):
        rotor = self.rotor(min_azimuth_deg=300.0, max_azimuth_deg=60.0)

        for az_deg in (300.0, 350.0, 0.0, 60.0):
            self.assertTrue(rotor.azimuth_in_window(az_deg), az_deg)
        for az_deg in (61.0, 180.0, 299.0):
            self.assertFalse(rotor.azimuth_in_window(az_deg), az_deg)

    def test_point_in_bounds_checks_the_elevation_threshold(self):
        rotor = self.rotor(min_elevation_deg=15.0)

        self.assertTrue(rotor.point_in_bounds(120.0, 15.0))
        self.assertFalse(rotor.point_in_bounds(120.0, 14.9))

    def test_half_an_azimuth_window_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.rotor(min_azimuth_deg=300.0).clean()

        with self.assertRaises(ValidationError):
            self.rotor(max_azimuth_deg=60.0).clean()

    def test_both_edges_or_neither_is_accepted(self):
        self.rotor().clean()
        self.rotor(min_azimuth_deg=300.0, max_azimuth_deg=60.0).clean()


class MergeTrajectoryTests(SimpleTestCase):
    def test_nothing_pending_keeps_what_arrives(self):
        incoming = rising_pass(2)

        self.assertEqual(merge_trajectory([], incoming), incoming)

    def test_an_empty_message_leaves_the_plan_alone(self):
        pending = rising_pass(2)

        self.assertEqual(merge_trajectory(pending, []), pending)

    def test_a_single_point_extends_the_tail(self):
        pending = rising_pass(2)
        incoming = [(at(6000), 140.0, 60.0)]

        self.assertEqual(merge_trajectory(pending, incoming), pending + incoming)

    def test_what_arrives_wins_over_the_stretch_it_covers(self):
        pending = rising_pass(4)
        incoming = [(at(5000), 999.0, 88.0)]

        merged = merge_trajectory(pending, incoming)

        # The pending points from 5000 on are gone; the earlier ones survive.
        self.assertEqual(merged, pending[:2] + incoming)

    def test_a_message_starting_first_replaces_everything(self):
        pending = rising_pass(4)
        incoming = [(at(1000), 10.0, 10.0), (at(2000), 11.0, 11.0)]

        self.assertEqual(merge_trajectory(pending, incoming), incoming)


class PlanForRotorTests(SimpleTestCase):
    def rotor(self, **overrides):
        overrides.setdefault('min_elevation_deg', 10.0)
        return Rotor(device_id=DEVICE_ID, **overrides)

    def test_points_that_already_passed_are_dropped(self):
        trajectory = [(at(-5000), 120.0, 30.0)] + rising_pass(3)

        batches, _, _ = plan_for_rotor(self.rotor(), trajectory, NOW_MS)

        self.assertEqual(batches[0].t0_ms, at(3000))

    def test_a_whole_trajectory_holds_after_the_last_point(self):
        trajectory = rising_pass(6)

        batches, hold_at_ms, reason = plan_for_rotor(self.rotor(), trajectory, NOW_MS)

        self.assertTrue(batches)
        self.assertEqual(hold_at_ms, trajectory[-1][0] + HOLD_GRACE_MS)
        self.assertEqual(reason, DispatchOrder.Reason.END)

    def test_elevation_threshold_cuts_the_trajectory_at_the_edge(self):
        # Climbs, then drops back under the threshold on the fourth point.
        trajectory = [
            (at(3000), 120.0, 30.0),
            (at(4000), 121.0, 25.0),
            (at(5000), 122.0, 20.0),
            (at(6000), 123.0, 5.0),
            (at(7000), 124.0, 2.0),
        ]

        batches, hold_at_ms, reason = plan_for_rotor(self.rotor(min_elevation_deg=15.0), trajectory, NOW_MS)

        self.assertEqual(reason, DispatchOrder.Reason.LIMITS)
        # No grace: the antenna stops exactly where the target leaves the window.
        self.assertEqual(hold_at_ms, at(6000))
        self.assertEqual([point[0] for point in batches[0].points], [0, 1000, 2000])

    def test_azimuth_window_cuts_the_trajectory_too(self):
        trajectory = [
            (at(3000), 350.0, 30.0),
            (at(4000), 10.0, 30.0),
            (at(5000), 120.0, 30.0),
        ]

        _, hold_at_ms, reason = plan_for_rotor(
            self.rotor(min_azimuth_deg=300.0, max_azimuth_deg=60.0), trajectory, NOW_MS,
        )

        self.assertEqual(reason, DispatchOrder.Reason.LIMITS)
        self.assertEqual(hold_at_ms, at(5000))

    def test_everything_expired_means_stop_now(self):
        trajectory = [(at(-2000), 120.0, 30.0), (at(-1000), 121.0, 31.0)]

        batches, hold_at_ms, reason = plan_for_rotor(self.rotor(), trajectory, NOW_MS)

        self.assertEqual(batches, [])
        self.assertEqual(hold_at_ms, NOW_MS)
        self.assertEqual(reason, DispatchOrder.Reason.EXPIRED)

    def test_a_first_point_out_of_bounds_means_stop_now(self):
        trajectory = [(at(3000), 120.0, 2.0), (at(4000), 121.0, 1.0)]

        batches, hold_at_ms, reason = plan_for_rotor(self.rotor(min_elevation_deg=15.0), trajectory, NOW_MS)

        self.assertEqual(batches, [])
        self.assertEqual(hold_at_ms, NOW_MS)
        self.assertEqual(reason, DispatchOrder.Reason.LIMITS)

    def test_a_trajectory_the_encoder_refuses_is_rejected(self):
        trajectory = [(at(3000), 120.0, 95.0)]

        with self.assertLogs(LOGGER, level='WARNING'):
            self.assertIsNone(plan_for_rotor(self.rotor(), trajectory, NOW_MS))


class RecordOrderTests(TestCase):
    def setUp(self):
        self.rotor = Rotor.objects.create(device_id=DEVICE_ID)
        self.plugin = PluginInstance.objects.create(name='tracker-0', plugin_type='file_tracker')

    def test_a_batch_row_carries_its_points_and_the_instant_it_covers(self):
        points = ((0, 12345, 4500), (1000, 12400, 4530), (2000, 12455, 4560))

        order = record_order(
            self.rotor, self.plugin, DispatchOrder.Kind.BATCH, NOW_MS, at(-2000), points,
        )
        order.refresh_from_db()

        self.assertEqual(order.kind, DispatchOrder.Kind.BATCH)
        self.assertEqual(order.t0_ms, NOW_MS)
        self.assertEqual(order.t_sent_ms, at(-2000))
        self.assertEqual(order.t_end_ms, at(2000))
        self.assertEqual(order.points, [[0, 12345, 4500], [1000, 12400, 4530], [2000, 12455, 4560]])
        self.assertEqual(order.reason, '')
        self.assertIsNotNone(order.created_at)

    def test_a_hold_row_carries_no_points_and_ends_where_it_starts(self):
        order = record_order(
            self.rotor, self.plugin, DispatchOrder.Kind.HOLD, NOW_MS, NOW_MS, (),
            reason=DispatchOrder.Reason.LIMITS,
        )

        self.assertEqual(order.points, [])
        self.assertEqual(order.t_end_ms, NOW_MS)
        self.assertEqual(order.reason, DispatchOrder.Reason.LIMITS)

    def test_a_rotor_with_orders_cannot_be_deleted(self):
        record_order(self.rotor, self.plugin, DispatchOrder.Kind.HOLD, NOW_MS, NOW_MS, ())

        with self.assertRaises(ProtectedError):
            self.rotor.delete()

    def test_a_plugin_with_orders_cannot_be_deleted(self):
        record_order(self.rotor, self.plugin, DispatchOrder.Kind.HOLD, NOW_MS, NOW_MS, ())

        with self.assertRaises(ProtectedError):
            self.plugin.delete()


class RotorExclusivityTests(TestCase):
    """RF-31.1: assigning the rotor is how the user picks who drives the motors."""

    def setUp(self):
        self.rotor = Rotor.objects.create(device_id=DEVICE_ID)

    def plugin(self, name, status=PluginInstance.Status.RUNNING, rotor=UNSET):
        return PluginInstance(
            name=name,
            plugin_type='file_tracker',
            status=status,
            rotor=self.rotor if rotor is UNSET else rotor,
        )

    def test_a_second_running_plugin_on_the_same_rotor_is_rejected(self):
        self.plugin('tracker-0').save()

        with self.assertRaises(ValidationError):
            self.plugin('tracker-1').clean()

    def test_a_stopped_plugin_may_share_the_rotor(self):
        self.plugin('tracker-0', status=PluginInstance.Status.STOPPED).save()

        self.plugin('tracker-1').clean()

    def test_re_saving_the_same_instance_is_fine(self):
        plugin = self.plugin('tracker-0')
        plugin.save()

        plugin.clean()

    def test_a_plugin_without_a_rotor_is_never_in_conflict(self):
        self.plugin('tracker-0').save()

        self.plugin('tracker-1', rotor=None).clean()


@contextmanager
def frozen(moment_ms=NOW_MS):
    """Both clocks the command reads, stopped on the same instant."""
    with patch(f'{MODULE}.now_ms', return_value=moment_ms), \
            patch(f'{MODULE}.time.time', return_value=moment_ms / 1000):
        yield


@patch(f'{MODULE}.close_old_connections')
class MessageHandlingTests(TestCase):
    def setUp(self):
        self.rotor = Rotor.objects.create(device_id=DEVICE_ID, min_elevation_deg=10.0)
        self.plugin = PluginInstance.objects.create(
            name='tracker-0', plugin_type='file_tracker', rotor=self.rotor,
        )
        self.command = Command()
        self.command.client = MagicMock()

    def message(self, points=None, topic=None):
        return SimpleNamespace(
            topic=topic or f'plugin/{self.plugin.plugin_uuid}/coordinates/polar',
            payload=polar_payload(points or rising_pass()),
        )

    def deliver(self, message=None, timer_cls=None):
        with frozen():
            if timer_cls is None:
                with patch(f'{MODULE}.threading.Timer') as timer_cls:
                    self.command.on_message(None, None, message or self.message())
                    return timer_cls
            self.command.on_message(None, None, message or self.message())
            return timer_cls

    def schedule(self):
        return self.command._schedules[self.rotor.pk]

    def test_a_trajectory_installs_a_schedule_and_arms_one_timer(self, _close):
        timer_cls = self.deliver()

        self.assertIn(self.rotor.pk, self.command._schedules)
        self.assertTrue(self.schedule().batches)
        timer_cls.assert_called_once()
        timer_cls.return_value.start.assert_called_once()

    def test_the_first_batch_is_armed_for_its_lead_time(self, _close):
        timer_cls = self.deliver()

        # First point 3 s out, published 2 s ahead of it.
        delay = timer_cls.call_args.args[0]
        self.assertAlmostEqual(delay, 1.0, places=3)

    def test_an_overdue_batch_goes_out_immediately(self, _close):
        timer_cls = self.deliver(self.message(points=[(at(500), 120.0, 30.0), (at(1500), 121.0, 31.0)]))

        self.assertEqual(timer_cls.call_args.args[0], 0.0)

    def test_one_point_at_a_time_accumulates_instead_of_replacing(self, _close):
        with patch(f'{MODULE}.threading.Timer'):
            for offset_ms in (3000, 4000, 5000):
                self.deliver(
                    self.message(points=[(at(offset_ms), 120.0, 30.0)]),
                    timer_cls=True,
                )

        # With replace semantics this would be a single point, and the HOLD of
        # each message would fire before the next one arrived.
        self.assertEqual([point[0] for point in self.schedule().trajectory],
                         [at(3000), at(4000), at(5000)])
        self.assertEqual(self.schedule().reason, DispatchOrder.Reason.END)
        self.assertFalse(DispatchOrder.objects.exists())

    def test_a_new_trajectory_cancels_what_was_armed(self, _close):
        with patch(f'{MODULE}.threading.Timer') as timer_cls:
            self.deliver(timer_cls=timer_cls)
            first = self.schedule()
            self.deliver(timer_cls=timer_cls)

        self.assertIsNot(self.schedule(), first)
        timer_cls.return_value.cancel.assert_called_once()

    def test_a_message_on_an_unexpected_topic_is_rejected(self, _close):
        with self.assertLogs(MODULE, level='WARNING'):
            self.deliver(self.message(topic=f'plugin/{self.plugin.plugin_uuid}/coordinates/raw'))

        self.assertEqual(self.command.stats['rejected'], 1)
        self.assertFalse(self.command._schedules)

    def test_an_unknown_plugin_is_rejected(self, _close):
        with self.assertLogs(LOGGER, level='WARNING'):
            self.deliver(self.message(topic='plugin/00000000-0000-4000-8000-000000000000/coordinates/polar'))

        self.assertEqual(self.command.stats['rejected'], 1)

    def test_a_plugin_without_a_rotor_is_ignored(self, _close):
        orphan = PluginInstance.objects.create(name='tracker-1', plugin_type='file_tracker')

        with self.assertLogs(LOGGER, level='INFO'):
            self.deliver(self.message(topic=f'plugin/{orphan.plugin_uuid}/coordinates/polar'))

        self.assertEqual(self.command.stats['rejected'], 1)
        self.assertFalse(self.command._schedules)

    def test_a_malformed_payload_does_not_raise(self, _close):
        message = SimpleNamespace(
            topic=f'plugin/{self.plugin.plugin_uuid}/coordinates/polar', payload=b'{"roto',
        )

        with self.assertLogs(LOGGER, level='WARNING'):
            self.deliver(message)

        self.assertEqual(self.command.stats['rejected'], 1)

    def test_a_database_failure_is_logged_and_swallowed(self, _close):
        with patch(f'{MODULE}.resolve_rotor', side_effect=OperationalError('postgres caido')):
            with self.assertLogs(MODULE, level='ERROR'):
                self.deliver()

        self.assertEqual(self.command.stats['failed'], 1)


@patch(f'{MODULE}.close_old_connections')
class PublishingTests(TestCase):
    def setUp(self):
        self.rotor = Rotor.objects.create(device_id=DEVICE_ID, min_elevation_deg=10.0)
        self.plugin = PluginInstance.objects.create(
            name='tracker-0', plugin_type='file_tracker', rotor=self.rotor,
        )
        self.command = Command()
        self.command.client = MagicMock()

        # The class-level patch only covers test methods, and close_old_connections
        # would drop the connection this TestCase's transaction runs on.
        with frozen(), patch(f'{MODULE}.threading.Timer'), patch(f'{MODULE}.close_old_connections'):
            self.command.on_message(None, None, SimpleNamespace(
                topic=f'plugin/{self.plugin.plugin_uuid}/coordinates/polar',
                payload=polar_payload(rising_pass(count=3)),
            ))
        self.schedule = self.command._schedules[self.rotor.pk]

    def fire(self, times=1):
        with frozen(), patch(f'{MODULE}.threading.Timer'):
            for _ in range(times):
                self.command._fire(self.schedule)

    def test_a_batch_goes_out_on_the_board_topic_with_qos_1_and_no_retain(self, _close):
        self.fire()

        topic, payload = self.command.client.publish.call_args.args
        self.assertEqual(topic, f'device/{DEVICE_ID}/coordinates/polar')
        self.assertEqual(payload[0], 0x50)
        self.assertEqual(self.command.client.publish.call_args.kwargs, {'qos': 1, 'retain': False})

    def test_a_batch_is_recorded_with_what_went_on_the_wire(self, _close):
        self.fire()

        order = DispatchOrder.objects.get()
        self.assertEqual(order.kind, DispatchOrder.Kind.BATCH)
        self.assertEqual(order.rotor, self.rotor)
        self.assertEqual(order.plugin, self.plugin)
        self.assertEqual(order.t_sent_ms, NOW_MS)
        self.assertEqual(order.points[0], [0, 12000, 2000])
        self.assertEqual(self.command.stats['dispatched'], 1)

    def test_the_last_message_of_a_trajectory_is_a_hold(self, _close):
        self.fire(times=len(self.schedule.batches) + 1)

        hold = DispatchOrder.objects.filter(kind=DispatchOrder.Kind.HOLD).get()
        self.assertEqual(hold.points, [])
        self.assertEqual(hold.reason, DispatchOrder.Reason.END)
        self.assertEqual(hold.t0_ms, hold.t_sent_ms)
        self.assertEqual(self.command.stats['held'], 1)

    def test_the_schedule_is_dropped_once_the_hold_has_gone_out(self, _close):
        self.fire(times=len(self.schedule.batches) + 1)

        self.assertFalse(self.command._schedules)

    def test_a_replaced_schedule_never_publishes(self, _close):
        self.command._schedules[self.rotor.pk] = 'someone else'

        self.fire()

        self.command.client.publish.assert_not_called()
        self.assertFalse(DispatchOrder.objects.exists())


@override_settings(MQTT_CONFIG={'HOST': 'broker', 'PORT': 1884, 'USERNAME': 'u', 'PASSWORD': 'p'})
class CommandTests(SimpleTestCase):
    def run_command(self, *args, command='mqtt_dispatch'):
        with patch(f'{MODULE}.mqtt.Client') as client_cls, \
                patch(f'{MODULE}.wait_for_migrations') as wait, \
                patch(f'{MODULE}.signal.signal'), \
                patch(f'{MODULE}.logging.basicConfig'):
            call_command(command, *args)
        return client_cls.return_value, wait

    def test_waits_for_migrations_then_connects_with_credentials(self):
        paho, wait = self.run_command()

        wait.assert_called_once()
        paho.username_pw_set.assert_called_once_with('u', 'p')
        paho.connect.assert_called_once_with('broker', 1884, 60)

    def test_subscribes_to_the_polar_topic_on_connect(self):
        command = Command()
        paho = MagicMock()

        command.on_connect(paho, None, None, 0)

        paho.subscribe.assert_called_once_with([(POLAR_TOPIC, 1)])

    def test_does_not_subscribe_when_connection_fails(self):
        command = Command()
        paho = MagicMock()

        with self.assertLogs(MODULE, level='ERROR'):
            command.on_connect(paho, None, None, 5)

        paho.subscribe.assert_not_called()

    def test_topic_option_replaces_the_defaults(self):
        command = Command()

        self.run_command('--topic', 'plugin/+/coordinates/polar', '--qos', '0', command=command)

        self.assertEqual(command.topics, ['plugin/+/coordinates/polar'])
        self.assertEqual(command.qos, 0)
