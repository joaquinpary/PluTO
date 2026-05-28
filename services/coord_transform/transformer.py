import logging
import math
from typing import Union
import numpy as np
from skyfield.api import load, wgs84
from skyfield.positionlib import Geocentric

from models import (
    CartesianCoordinatePoint,
    GeoCoordinatePoint,
    PolarCoordinatePoint,
    Station,
    CoordinateType,
    CoordinateFormat
)

logger = logging.getLogger(__name__)

# Cargar la escala de tiempo (se descargará un archivo leapseconds la primera vez)
ts = load.timescale()

# Distancia en km de 1 UA (para conversión de skyfield)
AU_KM = 149597870.700

def transform_eci_cartesian_to_polar(point: CartesianCoordinatePoint, station: Station) -> PolarCoordinatePoint:
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

def transform_ecef_cartesian_to_polar(point: CartesianCoordinatePoint, station: Station) -> PolarCoordinatePoint:
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
    
    # Transformar el resultante ENU a Polar (simulando un CartesianCoordinatePoint de tipo ENU)
    enu_point = CartesianCoordinatePoint(timestamp=point.timestamp, x=e, y=n, z=u)
    return transform_enu_cartesian_to_polar(enu_point, station)

def transform_ecef_geo_to_polar(point: GeoCoordinatePoint, station: Station) -> PolarCoordinatePoint:
    t = ts.from_datetime(point.timestamp)
    target = wgs84.latlon(point.lat, point.lon, elevation_m=point.alt)
    observer = wgs84.latlon(station.lat, station.lon, elevation_m=station.alt)
    
    # Difference
    diff = target.at(t) - observer.at(t)
    alt, az, distance = diff.altaz()
    
    return PolarCoordinatePoint(
        timestamp=point.timestamp,
        az=az.degrees,
        el=alt.degrees,
        range=distance.km
    )

def transform_enu_cartesian_to_polar(point: CartesianCoordinatePoint, station: Station) -> PolarCoordinatePoint:
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

def transform_enu_polar_to_polar(point: PolarCoordinatePoint, station: Station) -> PolarCoordinatePoint:
    return PolarCoordinatePoint(
        timestamp=point.timestamp,
        az=point.az,
        el=point.el,
        range=point.range
    )

def transform_coordinates(
    point: Union[CartesianCoordinatePoint, GeoCoordinatePoint, PolarCoordinatePoint],
    station: Station,
    coord_type: CoordinateType,
    coord_format: CoordinateFormat
) -> PolarCoordinatePoint:
    if coord_type == CoordinateType.ECI and coord_format == CoordinateFormat.CARTESIAN:
        return transform_eci_cartesian_to_polar(point, station)
    elif coord_type == CoordinateType.ECEF and coord_format == CoordinateFormat.CARTESIAN:
        return transform_ecef_cartesian_to_polar(point, station)
    elif coord_type == CoordinateType.ECEF and coord_format == CoordinateFormat.GEO:
        return transform_ecef_geo_to_polar(point, station)
    elif coord_type == CoordinateType.ENU and coord_format == CoordinateFormat.CARTESIAN:
        return transform_enu_cartesian_to_polar(point, station)
    elif coord_type == CoordinateType.ENU and coord_format == CoordinateFormat.POLAR:
        return transform_enu_polar_to_polar(point, station)
    else:
        raise ValueError(f"Tipo de coordenada no soportado: {coord_type} - {coord_format}")
