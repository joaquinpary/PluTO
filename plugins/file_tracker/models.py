from datetime import datetime
from enum import Enum
from typing import List, Union

from pydantic import BaseModel, Field, model_validator

class CoordinateType(str, Enum):
    ECI = "ECI"
    ECEF = "ECEF"
    ENU = "ENU"

class CoordinateFormat(str, Enum):
    GEO = "GEO"
    CARTESIAN = "CARTESIAN"
    POLAR = "POLAR"

# Valid combinations:
# ECEF + CARTESIAN
# ECEF + GEO
# ECI  + CARTESIAN
# ENU  + POLAR
# ENU  + CARTESIAN

class Station(BaseModel):
    lat: float = Field(..., description="Latitud en grados")
    lon: float = Field(..., description="Longitud en grados")
    alt: float = Field(..., description="Altitud en metros")

class CartesianCoordinatePoint(BaseModel):
    timestamp: datetime = Field(..., description="Timestamp en formato ISO 8601 (UTC)")
    x: float = Field(..., description="Coordenada X")
    y: float = Field(..., description="Coordenada Y")
    z: float = Field(..., description="Coordenada Z")

class GeoCoordinatePoint(BaseModel):
    timestamp: datetime = Field(..., description="Timestamp en formato ISO 8601 (UTC)")
    lat: float = Field(..., description="Latitud del objetivo en grados")
    lon: float = Field(..., description="Longitud del objetivo en grados")
    alt: float = Field(..., description="Altitud del objetivo en metros")

class PolarCoordinatePoint(BaseModel):
    timestamp: datetime = Field(..., description="Timestamp en formato ISO 8601 (UTC)")
    az: float = Field(..., description="Azimuth en grados")
    el: float = Field(..., description="Elevación en grados")
    range: float = Field(..., description="Rango en km")

class RawCoordinatesPayload(BaseModel):
    type: CoordinateType
    coord_format: CoordinateFormat = Field(..., description="Formato de coordenadas del objetivo")
    station: Station
    coordinates: List[Union[CartesianCoordinatePoint, GeoCoordinatePoint, PolarCoordinatePoint]]

    @model_validator(mode="after")
    def validate_type_format_combination(self):
        valid_combinations = {
            (CoordinateType.ECEF, CoordinateFormat.CARTESIAN),
            (CoordinateType.ECEF, CoordinateFormat.GEO),
            (CoordinateType.ECI,  CoordinateFormat.CARTESIAN),
            (CoordinateType.ENU,  CoordinateFormat.POLAR),
            (CoordinateType.ENU,  CoordinateFormat.CARTESIAN),
        }
        if (self.type, self.coord_format) not in valid_combinations:
            raise ValueError(
                f"Invalid combination type={self.type} + coord_format={self.coord_format}. "
                f"Valid: {[f'{t}+{f}' for t, f in sorted(valid_combinations, key=lambda x: str(x))]}"
            )
        return self

    @model_validator(mode="after")
    def validate_coordinates_match_format(self):
        if self.coord_format == CoordinateFormat.GEO:
            expected_type = GeoCoordinatePoint
        elif self.coord_format == CoordinateFormat.CARTESIAN:
            expected_type = CartesianCoordinatePoint
        else:
            expected_type = PolarCoordinatePoint
        if any(not isinstance(point, expected_type) for point in self.coordinates):
            raise ValueError(f"coordinates must match coord_format={self.coord_format}")
        return self
