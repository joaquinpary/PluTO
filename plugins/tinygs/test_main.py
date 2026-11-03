import os
import unittest
from unittest.mock import MagicMock, patch

import main

LOCATION = '{"lat": -31.4201, "lon": -64.1888, "alt": 470}'


class BuildStationTests(unittest.TestCase):
    def station(self, **environment):
        with patch.dict(os.environ, environment, clear=True):
            return main.build_station_from_env()

    def test_reads_the_location_pluto_sends(self):
        self.assertEqual(self.station(STATION_COORDINATES=LOCATION), {'lat': -31.4201, 'lon': -64.1888, 'alt': 470.0})

    def test_the_loose_variables_still_work(self):
        self.assertEqual(self.station(STATION_LAT='-31.4', STATION_LON='-64.2'), {'lat': -31.4, 'lon': -64.2, 'alt': 0.0})

    def test_without_a_location_there_is_no_station(self):
        # What PluTO sends for an instance whose board has no location.
        self.assertIsNone(self.station())

    def test_an_unreadable_location_is_no_station(self):
        with self.assertLogs('tinygs_main', level='WARNING'):
            self.assertIsNone(self.station(STATION_COORDINATES='not json'))


@patch('main.signal.signal')
@patch('main.antenna_from_environment')
@patch('main.from_environment', return_value=(MagicMock(), MagicMock(device_id='a1b2c3d4e5f6')))
@patch('main.Tracker')
@patch('main.TinyGSMQTTClient')
class MainTests(unittest.TestCase):
    """A plugin bound to a board: the only case in which it follows passes."""

    def run_main(self, **environment):
        base = {'TINYGS_DEVICE': 'My_TinyGS', 'INSTANCE_ID': 'uuid-1'}
        with patch.dict(os.environ, {**base, **environment}, clear=True):
            return main.main()

    def test_without_a_location_it_relays_packets_and_computes_no_passes(self, client_cls, tracker_cls, *_):
        with self.assertLogs('tinygs_main', level='WARNING'):
            self.assertEqual(self.run_main(), 0)

        tracker_cls.assert_not_called()
        client_cls.return_value.start.assert_called_once()

    def test_with_a_location_it_computes_passes(self, client_cls, tracker_cls, *_):
        self.assertEqual(self.run_main(STATION_COORDINATES=LOCATION), 0)

        self.assertEqual(tracker_cls.call_args.kwargs['station'], {'lat': -31.4201, 'lon': -64.1888, 'alt': 470.0})
        tracker_cls.return_value.start.assert_called_once()
        self.assertIs(client_cls.return_value.tracker, tracker_cls.return_value)
        client_cls.return_value.start.assert_called_once()
