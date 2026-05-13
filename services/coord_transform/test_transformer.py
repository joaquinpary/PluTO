import unittest
from datetime import datetime, timezone
import math
from models import CoordinatePoint, Station, CoordinateType
from transformer import (
    transform_enu_to_polar,
    transform_ecef_to_polar,
    transform_coordinates
)

class TestTransformer(unittest.TestCase):
    def setUp(self):
        self.station = Station(lat=-34.921, lon=-57.954, alt=20.0)
        self.timestamp = datetime(2026, 5, 8, 15, 0, 0, tzinfo=timezone.utc)

    def test_enu_to_polar_north(self):
        # Punto directamente al norte, a 100km, elevación 0
        pt = CoordinatePoint(timestamp=self.timestamp, x=0.0, y=100.0, z=0.0)
        polar = transform_enu_to_polar(pt, self.station)
        
        self.assertAlmostEqual(polar.az, 0.0, places=2)
        self.assertAlmostEqual(polar.el, 0.0, places=2)
        self.assertAlmostEqual(polar.range, 100.0, places=2)

    def test_enu_to_polar_east(self):
        # Punto directamente al este, a 50km, 50km arriba
        pt = CoordinatePoint(timestamp=self.timestamp, x=50.0, y=0.0, z=50.0)
        polar = transform_enu_to_polar(pt, self.station)
        
        self.assertAlmostEqual(polar.az, 90.0, places=2)
        self.assertAlmostEqual(polar.el, 45.0, places=2) # 45 grados de elevación
        self.assertAlmostEqual(polar.range, math.sqrt(50**2 + 50**2), places=2)

    def test_polar_pass_through(self):
        pt = CoordinatePoint(timestamp=self.timestamp, x=120.5, y=45.2, z=1500.0)
        polar = transform_coordinates(pt, self.station, CoordinateType.POLAR)
        
        self.assertEqual(polar.az, 120.5)
        self.assertEqual(polar.el, 45.2)
        self.assertEqual(polar.range, 1500.0)

    # Nota: No se hace un test unitario exhaustivo de ECI/ECEF porque requiere 
    # la carga local de datos de efemérides (leapseconds de skyfield),
    # pero sí se puede comprobar que la función expone la firma correcta.

if __name__ == '__main__':
    unittest.main()
