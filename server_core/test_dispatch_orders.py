from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.test import SimpleTestCase, TestCase

from .dispatch_orders import record_order
from .models import DispatchOrder, PluginInstance, Rotor

DEVICE_ID = 'a1b2c3d4e5f6'

# 2026-09-18T20:30:00Z.
NOW_MS = 1789763400000

UNSET = object()


def at(offset_ms):
    return NOW_MS + offset_ms


class RecordOrderTests(TestCase):
    def setUp(self):
        self.rotor = Rotor.objects.create(device_id=DEVICE_ID)
        self.plugin = PluginInstance.objects.create(name='tracker-0', plugin_type='file_tracker')

    def test_a_batch_row_carries_its_points_and_the_instant_it_covers(self):
        points = ((0, 12345, 4500), (1000, 12400, 4530), (2000, 12455, 4560))

        order = record_order(self.rotor, self.plugin, DispatchOrder.Kind.BATCH, NOW_MS, at(-2000), points)
        order.refresh_from_db()

        self.assertEqual(order.kind, DispatchOrder.Kind.BATCH)
        self.assertEqual((order.t0_ms, order.t_sent_ms, order.t_end_ms), (NOW_MS, at(-2000), at(2000)))
        self.assertEqual(order.points, [[0, 12345, 4500], [1000, 12400, 4530], [2000, 12455, 4560]])
        self.assertEqual(order.reason, '')
        self.assertIsNotNone(order.created_at)

    def test_a_hold_row_carries_no_points_and_ends_where_it_starts(self):
        order = record_order(
            self.rotor, self.plugin, DispatchOrder.Kind.HOLD, NOW_MS, NOW_MS, (),
            reason=DispatchOrder.Reason.STOPPED,
        )

        self.assertEqual(order.points, [])
        self.assertEqual(order.t_end_ms, NOW_MS)
        self.assertEqual(order.reason, DispatchOrder.Reason.STOPPED)

    def test_a_rotor_with_orders_cannot_be_deleted(self):
        record_order(self.rotor, self.plugin, DispatchOrder.Kind.HOLD, NOW_MS, NOW_MS, ())

        with self.assertRaises(ProtectedError):
            self.rotor.delete()

    def test_a_plugin_with_orders_cannot_be_deleted(self):
        record_order(self.rotor, self.plugin, DispatchOrder.Kind.HOLD, NOW_MS, NOW_MS, ())

        with self.assertRaises(ProtectedError):
            self.plugin.delete()


class RotorWindowTests(SimpleTestCase):
    def test_half_an_azimuth_window_is_rejected(self):
        with self.assertRaises(ValidationError):
            Rotor(device_id=DEVICE_ID, min_azimuth_deg=300.0).clean()

        with self.assertRaises(ValidationError):
            Rotor(device_id=DEVICE_ID, max_azimuth_deg=60.0).clean()

    def test_both_edges_or_neither_is_accepted(self):
        Rotor(device_id=DEVICE_ID).clean()
        Rotor(device_id=DEVICE_ID, min_azimuth_deg=300.0, max_azimuth_deg=60.0).clean()


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
