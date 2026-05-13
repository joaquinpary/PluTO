from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

class CoordinateType(str, Enum):
    ECI = "ECI"
    ECEF = "ECEF"
    ENU = "ENU"
    POLAR = "POLAR"

class Station(BaseModel):
    lat: float = Field(..., description="Latitud en grados")
    lon: float = Field(..., description="Longitud en grados")
    alt: float = Field(..., description="Altitud en metros")

class CoordinatePoint(BaseModel):
    timestamp: datetime = Field(..., description="Timestamp en formato ISO 8601 (UTC)")
    x: float = Field(..., description="Coordenada X (km) o Azimuth (grados)")
    y: float = Field(..., description="Coordenada Y (km) o Elevación (grados)")
    z: float = Field(..., description="Coordenada Z (km) o Rango (km)")

class RawCoordinatesPayload(BaseModel):
    type: CoordinateType
    station: Station
    coordinates: List[CoordinatePoint]

class PolarCoordinatePoint(BaseModel):
    timestamp: datetime
    az: float = Field(..., description="Azimuth en grados")
    el: float = Field(..., description="Elevación en grados")
    range: Optional[float] = Field(None, description="Rango en km")

class PolarCoordinatesPayload(BaseModel):
    station: Station
    coordinates: List[PolarCoordinatePoint]
