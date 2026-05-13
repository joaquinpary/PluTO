import logging
import math
import numpy as np
from skyfield.api import load, wgs84
from skyfield.positionlib import Geocentric

from models import CoordinatePoint, Station, PolarCoordinatePoint

logger = logging.getLogger(__name__)

# Cargar la escala de tiempo (se descargará un archivo leapseconds la primera vez)
ts = load.timescale()

# Distancia en km de 1 UA (para conversión de skyfield)
AU_KM = 149597870.700

def transform_eci_to_polar(point: CoordinatePoint, station: Station) -> PolarCoordinatePoint:
    """
    Transforma coordenadas ECI (Earth-Centered Inertial) a Polares (Azimuth, Elevación, Rango)
    """
    t = ts.from_datetime(point.timestamp)
    
    # Skyfield maneja ICRF (similar a ECI) en Unidades Astronómicas (AU)
    pos_au = [point.x / AU_KM, point.y / AU_KM, point.z / AU_KM]
    geo = Geocentric(pos_au, t=t)
    
    # Definir la estación
    observer = wgs84.latlon(station.lat, station.lon, elevation_m=station.alt)
    
    # Calcular altitud (elevación) y azimuth
    difference = geo - observer.at(t)
    alt, az, distance = difference.altaz()
    
    return PolarCoordinatePoint(
        timestamp=point.timestamp,
        az=az.degrees,
        el=alt.degrees,
        range=distance.km
    )

def transform_ecef_to_polar(point: CoordinatePoint, station: Station) -> PolarCoordinatePoint:
    """
    Transforma coordenadas ECEF (Earth-Centered, Earth-Fixed) a Polares.
    Realiza un paso intermedio de ECEF a ENU, y luego a Polar.
    """
    observer = wgs84.latlon(station.lat, station.lon, elevation_m=station.alt)
    stat_ecef_km = observer.itrs_xyz.km
    
    dx = point.x - stat_ecef_km[0]
    dy = point.y - stat_ecef_km[1]
    dz = point.z - stat_ecef_km[2]
    
    lat_r = math.radians(station.lat)
    lon_r = math.radians(station.lon)
    
    slat, clat = math.sin(lat_r), math.cos(lat_r)
    slon, clon = math.sin(lon_r), math.cos(lon_r)
    
    # Matriz de rotación ECEF a ENU
    e = -slon * dx + clon * dy
    n = -slat * clon * dx - slat * slon * dy + clat * dz
    u = clat * clon * dx + clat * slon * dy + slat * dz
    
    # Transformar el resultante ENU a Polar (simulando un CoordinatePoint de tipo ENU)
    enu_point = CoordinatePoint(timestamp=point.timestamp, x=e, y=n, z=u)
    return transform_enu_to_polar(enu_point, station)

def transform_enu_to_polar(point: CoordinatePoint, station: Station) -> PolarCoordinatePoint:
    """
    Transforma coordenadas ENU (East, North, Up) a Polares.
    """
    e = point.x
    n = point.y
    u = point.z
    
    r = math.sqrt(e**2 + n**2 + u**2)
    el_rad = math.asin(u / r) if r != 0 else 0
    az_rad = math.atan2(e, n)
    
    az_deg = math.degrees(az_rad)
    if az_deg < 0:
        az_deg += 360.0
        
    el_deg = math.degrees(el_rad)
    
    return PolarCoordinatePoint(
        timestamp=point.timestamp,
        az=az_deg,
        el=el_deg,
        range=r
    )

def transform_polar(point: CoordinatePoint, station: Station) -> PolarCoordinatePoint:
    """
    Pasa las coordenadas Polar directas mapeando campos.
    """
    return PolarCoordinatePoint(
        timestamp=point.timestamp,
        az=point.x,
        el=point.y,
        range=point.z
    )

def transform_coordinates(point: CoordinatePoint, station: Station, coord_type: str) -> PolarCoordinatePoint:
    """
    Función de ruteo para transformar un punto basado en su tipo.
    """
    coord_type_upper = coord_type.upper()
    if coord_type_upper == "ECI":
        return transform_eci_to_polar(point, station)
    elif coord_type_upper == "ECEF":
        return transform_ecef_to_polar(point, station)
    elif coord_type_upper == "ENU":
        return transform_enu_to_polar(point, station)
    elif coord_type_upper == "POLAR":
        return transform_polar(point, station)
    else:
        raise ValueError(f"Tipo de coordenada no soportado: {coord_type}")
