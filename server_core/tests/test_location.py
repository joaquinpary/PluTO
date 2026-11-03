from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase

from ..models import Rotor

DEVICE_ID = 'a1b2c3d4e5f6'


class RotorLocationTests(SimpleTestCase):
    def test_a_board_without_latitude_or_longitude_has_no_location(self):
        for rotor in (
            Rotor(device_id=DEVICE_ID),
            Rotor(device_id=DEVICE_ID, latitude_deg=-31.4, altitude_m=470.0),
            Rotor(device_id=DEVICE_ID, longitude_deg=-64.2),
        ):
            with self.subTest(latitude=rotor.latitude_deg, longitude=rotor.longitude_deg):
                self.assertIsNone(rotor.location)

    def test_the_location_carries_the_altitude(self):
        rotor = Rotor(device_id=DEVICE_ID, latitude_deg=-31.4, longitude_deg=-64.2, altitude_m=470.0)

        self.assertEqual(rotor.location, {'lat': -31.4, 'lon': -64.2, 'alt': 470.0})

    def test_a_missing_altitude_counts_as_sea_level(self):
        rotor = Rotor(device_id=DEVICE_ID, latitude_deg=-31.4, longitude_deg=-64.2)

        self.assertEqual(rotor.location, {'lat': -31.4, 'lon': -64.2, 'alt': 0.0})

    def test_latitude_and_longitude_must_be_on_earth(self):
        for field, value in (
            ('latitude_deg', 90.5), ('latitude_deg', -91.0),
            ('longitude_deg', 180.5), ('longitude_deg', -181.0),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValidationError) as raised:
                    Rotor(device_id=DEVICE_ID, **{field: value}).clean_fields()
                self.assertIn(field, raised.exception.message_dict)

    def test_half_a_location_is_rejected(self):
        for rotor in (Rotor(device_id=DEVICE_ID, latitude_deg=-31.4), Rotor(device_id=DEVICE_ID, longitude_deg=-64.2)):
            with self.subTest(latitude=rotor.latitude_deg, longitude=rotor.longitude_deg):
                with self.assertRaises(ValidationError):
                    rotor.clean()

    def test_a_whole_location_or_none_is_fine(self):
        Rotor(device_id=DEVICE_ID).clean()
        Rotor(device_id=DEVICE_ID, latitude_deg=-31.4, longitude_deg=-64.2).clean()


class LocationMigrationTests(TransactionTestCase):
    """0009 moves the station from the instances to their boards."""

    before = [('server_core', '0008_rotor_location')]
    after = [('server_core', '0009_move_station_to_rotor')]

    def setUp(self):
        # A cleanup and not tearDown: it also runs when setUp fails halfway,
        # and every later test needs the database at its latest migration.
        self.addCleanup(self.migrate_to_latest)
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        old = executor.loader.project_state(self.before).apps
        OldRotor = old.get_model('server_core', 'Rotor')
        OldPlugin = old.get_model('server_core', 'PluginInstance')

        shared = OldRotor.objects.create(device_id='a1b2c3d4e5f6')
        OldPlugin.objects.create(name='first', plugin_type='tinygs', rotor=shared,
                                 station_lat=-31.4, station_lon=-64.2, station_alt=470.0)
        OldPlugin.objects.create(name='second', plugin_type='tinygs', rotor=shared,
                                 station_lat=10.0, station_lon=20.0, station_alt=5.0)
        located = OldRotor.objects.create(device_id='0a0b0c0d0e0f', latitude_deg=1.0, longitude_deg=2.0, altitude_m=3.0)
        OldPlugin.objects.create(name='late', plugin_type='tinygs', rotor=located,
                                 station_lat=-31.0, station_lon=-64.0, station_alt=400.0)
        never_set = OldRotor.objects.create(device_id='111111111111')
        OldPlugin.objects.create(name='never-set', plugin_type='tinygs', rotor=never_set)
        OldPlugin.objects.create(name='no-board', plugin_type='tinygs', station_lat=5.0, station_lon=5.0)

        # A new executor: the old one still believes the database is at 0008.
        executor = MigrationExecutor(connection)
        executor.migrate(self.after)
        self.apps = executor.loader.project_state(self.after).apps

    def migrate_to_latest(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def location(self, device_id):
        rotor = self.apps.get_model('server_core', 'Rotor').objects.get(device_id=device_id)
        return rotor.latitude_deg, rotor.longitude_deg, rotor.altitude_m

    def test_a_board_takes_the_location_of_its_oldest_instance(self):
        self.assertEqual(self.location('a1b2c3d4e5f6'), (-31.4, -64.2, 470.0))

    def test_a_board_that_already_has_a_location_keeps_it(self):
        self.assertEqual(self.location('0a0b0c0d0e0f'), (1.0, 2.0, 3.0))

    def test_the_old_default_is_not_a_location(self):
        self.assertEqual(self.location('111111111111'), (None, None, None))

    def test_the_instances_no_longer_have_a_station(self):
        Plugin = self.apps.get_model('server_core', 'PluginInstance')
        names = {field.name for field in Plugin._meta.get_fields()}

        self.assertFalse(names & {'station_lat', 'station_lon', 'station_alt'})
        self.assertEqual(Plugin.objects.count(), 5)
