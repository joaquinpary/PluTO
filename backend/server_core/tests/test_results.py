from datetime import date, datetime, timedelta, timezone

from django.test import SimpleTestCase, TestCase

from ..models import DispatchOrder, PluginData, PluginInstance, Rotor, RotorState
from ..results import pointing_error, reception_by_day, sky_distance_cdeg, split_passes, target_at
from .test_api import DEVICE_ID, OTHER_DEVICE_ID, FrontTestCase

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
# 2026-10-01T00:00:00Z, the instant the synthetic pass starts.
T0_MS = 1790812800000
START = datetime(2026, 9, 30, tzinfo=timezone.utc)
END = datetime(2026, 10, 2, tzinfo=timezone.utc)


def moment(ms):
    return EPOCH + timedelta(milliseconds=ms)


def iso(value):
    return value.isoformat().replace('+00:00', 'Z')


def batch(t0_ms, points, t_sent_ms=None):
    return DispatchOrder(kind=DispatchOrder.Kind.BATCH, t0_ms=t0_ms, t_sent_ms=t_sent_ms or t0_ms - 2000,
                         t_end_ms=t0_ms + points[-1][0], points=points)


def hold(t_sent_ms, reason=DispatchOrder.Reason.END):
    return DispatchOrder(kind=DispatchOrder.Kind.HOLD, t0_ms=t_sent_ms, t_sent_ms=t_sent_ms,
                         t_end_ms=t_sent_ms, points=[], reason=reason)


class SkyDistanceTests(SimpleTestCase):
    def test_the_examples_of_the_contract(self):
        # device-state.md §4.2: north does not jump, the zenith does not explode.
        self.assertEqual(sky_distance_cdeg(35990, 3000, 10, 3000), 17)
        self.assertEqual(sky_distance_cdeg(0, 8950, 18000, 8950), 100)

    def test_plain_cases(self):
        self.assertEqual(sky_distance_cdeg(12345, 4500, 12345, 4500), 0)
        self.assertEqual(sky_distance_cdeg(9000, 2000, 9000, 3000), 1000)
        self.assertEqual(sky_distance_cdeg(0, 0, 18000, 0), 18000)


class TargetAtTests(SimpleTestCase):
    def setUp(self):
        self.order = batch(1000, [[0, 35950, 1000], [1000, 50, 2000], [2000, 150, 3000]])

    def test_before_the_first_point_it_is_the_first_point(self):
        self.assertEqual(target_at(self.order, 0), (35950, 1000))

    def test_in_between_it_is_a_straight_line_the_short_way_across_north(self):
        self.assertEqual(target_at(self.order, 1500), (0, 1500))
        self.assertEqual(target_at(self.order, 2500), (100, 2500))

    def test_after_the_last_point_it_stays_there(self):
        self.assertEqual(target_at(self.order, 9000), (150, 3000))


class SplitPassesTests(SimpleTestCase):
    def test_a_pass_is_the_batches_up_to_the_hold_that_ends_them(self):
        first, second, third, fourth = (batch(ms, [[0, 0, 0]]) for ms in (1000, 2000, 5000, 9000))
        end, expired, limits = hold(3000), hold(4000, DispatchOrder.Reason.EXPIRED), hold(6000, DispatchOrder.Reason.LIMITS)

        passes = split_passes([first, second, end, expired, third, limits, fourth])

        # The HOLD without batches and the batch still waiting for its HOLD are not passes.
        self.assertEqual(passes, [([first, second], end), ([third], limits)])


class PointingErrorTests(TestCase):
    def setUp(self):
        self.rotor = Rotor.objects.create(device_id=DEVICE_ID)
        self.plugin = PluginInstance.objects.create(name='tinygs-1', plugin_type='tinygs')
        # A three-second pass: az 90.00 -> 92.00, el 30.00 -> 32.00, then HOLD.
        self.batch = self.order(DispatchOrder.Kind.BATCH, t0_ms=T0_MS, t_sent_ms=T0_MS - 2000,
                                points=[[0, 9000, 3000], [1000, 9100, 3100], [2000, 9200, 3200]])
        self.hold = self.order(DispatchOrder.Kind.HOLD, t0_ms=T0_MS + 3500, t_sent_ms=T0_MS + 3500,
                               reason=DispatchOrder.Reason.END)

    def order(self, kind, t0_ms, t_sent_ms, points=(), reason='', rotor=None):
        points = [list(point) for point in points]
        return DispatchOrder.objects.create(
            rotor=rotor or self.rotor, plugin=self.plugin, kind=kind, reason=reason, t0_ms=t0_ms,
            t_sent_ms=t_sent_ms, t_end_ms=t0_ms + (points[-1][0] if points else 0), points=points,
            created_at=moment(t_sent_ms),
        )

    def state(self, ms, az_cdeg, el_cdeg, t_sent_ms=T0_MS - 2000, accepted=True, **extra):
        return RotorState.objects.create(
            rotor=self.rotor, received_at=moment(ms + 40), board_time=moment(ms), clock_synced=True,
            mode='tracking', az_cdeg=az_cdeg, el_cdeg=el_cdeg, batch_accepted=accepted,
            payload={'batch': {'t_sent_ms': t_sent_ms, 'accepted': accepted}, **extra},
        )

    def test_without_meas_it_crosses_the_reported_position_with_the_order(self):
        self.state(T0_MS + 500, 9050, 3050)                          # on target: 0
        self.state(T0_MS + 1000, 9100, 3000)                         # 1.00 below: 100
        self.state(T0_MS + 1500, 0, 0, t_sent_ms=T0_MS - 99999)      # an order of another pass
        self.state(T0_MS + 1800, 0, 0, accepted=False)               # rejected: not what it executes

        passes = pointing_error(self.rotor, START, END)

        self.assertEqual(passes, [{
            'start': moment(T0_MS), 'end': moment(T0_MS + 3500), 'source': 'commanded',
            'samples': 2, 'mean_err_cdeg': 50.0, 'max_err_cdeg': 100,
        }])

    def test_with_meas_it_takes_the_error_the_board_measured(self):
        self.state(T0_MS + 500, 9050, 3050, meas={'az_cdeg': 9040, 'el_cdeg': 3030}, err_cdeg=30)
        self.state(T0_MS + 1000, 9100, 3100, meas={'az_cdeg': 9090, 'el_cdeg': 3080}, err_cdeg=50)
        # A tick without a reading does not turn the pass into a commanded one.
        self.state(T0_MS + 1500, 9150, 3150, meas=None, err_cdeg=None)

        passes = pointing_error(self.rotor, START, END)

        self.assertEqual(
            [(found['source'], found['samples'], found['mean_err_cdeg'], found['max_err_cdeg']) for found in passes],
            [('meas', 2, 40.0, 50)],
        )

    def test_a_pass_without_states_has_no_error(self):
        passes = pointing_error(self.rotor, START, END)

        self.assertEqual((passes[0]['samples'], passes[0]['mean_err_cdeg'], passes[0]['max_err_cdeg']), (0, None, None))

    def test_only_this_board_and_this_range(self):
        other = Rotor.objects.create(device_id=OTHER_DEVICE_ID)
        self.order(DispatchOrder.Kind.BATCH, T0_MS, T0_MS - 2000, points=[[0, 0, 0]], rotor=other)
        self.order(DispatchOrder.Kind.HOLD, T0_MS + 900, T0_MS + 900, rotor=other)

        self.assertEqual(len(pointing_error(self.rotor, START, END)), 1)
        self.assertEqual(pointing_error(self.rotor, END, END + timedelta(days=1)), [])


class ReceptionByDayTests(TestCase):
    def setUp(self):
        self.plugin = PluginInstance.objects.create(name='tinygs-1', plugin_type='tinygs')

    def rx(self, created_at, payload, message_type='rx', plugin=None):
        PluginData.objects.create(plugin=plugin or self.plugin, message_type=message_type,
                                  payload=payload, created_at=created_at)

    def test_groups_the_rx_data_per_utc_day_and_keeps_quiet_days(self):
        day1 = datetime(2026, 10, 1, 10, tzinfo=timezone.utc)
        day2 = datetime(2026, 10, 2, 23, 59, tzinfo=timezone.utc)
        self.rx(day1, {'rssi': -100, 'snr': 5, 'crc_error': False})
        self.rx(day1, {'rssi': -110, 'snr': 3, 'crc_error': True})
        self.rx(day2, {'crc_error': False})                          # no rssi nor snr
        self.rx(day1, {'satellite': 'NOAA 19'}, message_type='tracking')
        other = PluginInstance.objects.create(name='tinygs-2', plugin_type='tinygs')
        self.rx(day1, {'rssi': -50}, plugin=other)

        days = reception_by_day(self.plugin, datetime(2026, 10, 1, tzinfo=timezone.utc),
                                datetime(2026, 10, 4, tzinfo=timezone.utc))

        self.assertEqual(days, [
            {'date': date(2026, 10, 1), 'packets': 2, 'crc_errors': 1, 'rssi_mean': -105.0, 'snr_mean': 4.0},
            {'date': date(2026, 10, 2), 'packets': 1, 'crc_errors': 0, 'rssi_mean': None, 'snr_mean': None},
            {'date': date(2026, 10, 3), 'packets': 0, 'crc_errors': 0, 'rssi_mean': None, 'snr_mean': None},
        ])


class ResultsApiTests(FrontTestCase):
    def setUp(self):
        super().setUp()
        self.rotor = Rotor.objects.create(device_id=DEVICE_ID)
        self.plugin = PluginInstance.objects.create(name='tinygs-1', plugin_type='tinygs')

    def test_pointing_error(self):
        DispatchOrder.objects.create(rotor=self.rotor, plugin=self.plugin, kind=DispatchOrder.Kind.BATCH,
                                     t0_ms=T0_MS, t_sent_ms=T0_MS - 2000, t_end_ms=T0_MS,
                                     points=[[0, 9000, 3000]], created_at=moment(T0_MS - 2000))
        DispatchOrder.objects.create(rotor=self.rotor, plugin=self.plugin, kind=DispatchOrder.Kind.HOLD,
                                     reason='end', t0_ms=T0_MS + 1500, t_sent_ms=T0_MS + 1500,
                                     t_end_ms=T0_MS + 1500, created_at=moment(T0_MS + 1500))

        response = self.client.get('/api/results/pointing-error',
                                   {'board': DEVICE_ID, 'from': iso(START), 'to': iso(END)})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'passes': [{
            'start': '2026-10-01T00:00:00Z', 'end': '2026-10-01T00:00:01.500000Z', 'source': 'commanded',
            'samples': 0, 'mean_err_cdeg': None, 'max_err_cdeg': None,
        }]})

    def test_pointing_error_needs_a_known_board_and_a_range(self):
        missing = self.client.get('/api/results/pointing-error')
        unknown = self.client.get('/api/results/pointing-error',
                                  {'board': OTHER_DEVICE_ID, 'from': iso(START), 'to': iso(END)})

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(set(missing.json()), {'board', 'from', 'to'})
        self.assertEqual(unknown.status_code, 404)

    def test_reception(self):
        PluginData.objects.create(plugin=self.plugin, message_type='rx', payload={'rssi': -100, 'snr': 2.5},
                                  created_at=datetime(2026, 10, 1, 12, tzinfo=timezone.utc))

        response = self.client.get('/api/results/reception', {
            'plugin': str(self.plugin.plugin_uuid), 'from': '2026-10-01T00:00:00Z', 'to': '2026-10-02T00:00:00Z',
        })

        self.assertEqual(response.json(), {'days': [
            {'date': '2026-10-01', 'packets': 1, 'crc_errors': 0, 'rssi_mean': -100.0, 'snr_mean': 2.5},
        ]})

    def test_reception_of_an_unknown_plugin_is_not_found(self):
        response = self.client.get('/api/results/reception', {
            'plugin': '00000000-0000-4000-8000-000000000000', 'from': iso(START), 'to': iso(END),
        })

        self.assertEqual(response.status_code, 404)

    def test_pointing_error_csv(self):
        DispatchOrder.objects.create(rotor=self.rotor, plugin=self.plugin, kind=DispatchOrder.Kind.BATCH,
                                     t0_ms=T0_MS, t_sent_ms=T0_MS - 2000, t_end_ms=T0_MS,
                                     points=[[0, 9000, 3000]], created_at=moment(T0_MS - 2000))
        DispatchOrder.objects.create(rotor=self.rotor, plugin=self.plugin, kind=DispatchOrder.Kind.HOLD,
                                     reason='end', t0_ms=T0_MS + 1500, t_sent_ms=T0_MS + 1500,
                                     t_end_ms=T0_MS + 1500, created_at=moment(T0_MS + 1500))

        response = self.client.get('/api/results/pointing-error',
                                   {'board': DEVICE_ID, 'from': iso(START), 'to': iso(END), 'format': 'csv'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Disposition'], 'attachment; filename="pointing-error.csv"')
        self.assertEqual(response.content.decode().splitlines(), [
            'start,end,source,samples,mean_err_cdeg,max_err_cdeg',
            '2026-10-01T00:00:00Z,2026-10-01T00:00:01.500000Z,commanded,0,,',
        ])

    def test_reception_csv(self):
        PluginData.objects.create(plugin=self.plugin, message_type='rx', payload={'rssi': -100, 'snr': 2.5},
                                  created_at=datetime(2026, 10, 1, 12, tzinfo=timezone.utc))

        response = self.client.get('/api/results/reception', {
            'plugin': str(self.plugin.plugin_uuid), 'from': '2026-10-01T00:00:00Z', 'to': '2026-10-03T00:00:00Z',
            'format': 'csv',
        })

        self.assertEqual(response['Content-Disposition'], 'attachment; filename="reception.csv"')
        self.assertEqual(response.content.decode().splitlines(), [
            'date,packets,crc_errors,rssi_mean,snr_mean',
            '2026-10-01,1,0,-100.0,2.5',
            '2026-10-02,0,0,,',
        ])
