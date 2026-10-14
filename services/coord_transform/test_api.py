import unittest

from fastapi.testclient import TestClient

from api import app

STATION = {'lat': -31.4, 'lon': -64.2, 'alt': 400.0}


def raw_payload(**overrides):
    payload = {
        'type': 'ENU',
        'coord_format': 'POLAR',
        'station': STATION,
        'coordinates': [
            {'timestamp': '2026-10-13T14:00:00Z', 'az': 120.0, 'el': 15.0, 'range': 1500.0},
            {'timestamp': '2026-10-13T14:00:01Z', 'az': 121.0, 'el': 16.0, 'range': 1490.0},
        ],
    }
    payload.update(overrides)
    return payload


class TransformApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health(self):
        self.assertEqual(self.client.get('/health').json(), {'status': 'ok'})

    def test_returns_the_trajectory_in_az_el(self):
        response = self.client.post('/transform', json=raw_payload())

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['station'], STATION)
        self.assertEqual([(point['az'], point['el']) for point in body['coordinates']], [(120.0, 15.0), (121.0, 16.0)])
        self.assertTrue(body['coordinates'][0]['timestamp'].startswith('2026-10-13T14:00:00'))

    def test_a_cartesian_point_is_converted(self):
        response = self.client.post('/transform', json=raw_payload(
            coord_format='CARTESIAN',
            coordinates=[{'timestamp': '2026-10-13T14:00:00Z', 'x': 0.0, 'y': 100.0, 'z': 0.0}],
        ))

        point = response.json()['coordinates'][0]
        self.assertAlmostEqual(point['az'], 0.0, places=2)
        self.assertAlmostEqual(point['el'], 0.0, places=2)
        self.assertAlmostEqual(point['range'], 100.0, places=2)

    def test_an_unsupported_combination_is_rejected(self):
        response = self.client.post('/transform', json=raw_payload(type='ECI', coord_format='POLAR'))

        self.assertEqual(response.status_code, 422)

    def test_points_that_do_not_match_the_format_are_rejected(self):
        response = self.client.post('/transform', json=raw_payload(coord_format='CARTESIAN'))

        self.assertEqual(response.status_code, 422)

    def test_malformed_json_is_rejected(self):
        response = self.client.post('/transform', content=b'{"type"', headers={'Content-Type': 'application/json'})

        self.assertEqual(response.status_code, 422)


if __name__ == '__main__':
    unittest.main()
