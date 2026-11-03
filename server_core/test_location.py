from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .models import Rotor

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
