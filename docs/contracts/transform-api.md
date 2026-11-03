# Contrato de transformación: `POST /transform`

Cómo un plugin convierte su trayectoria a azimut y elevación vistos desde la estación.
`services/coord_transform` la recibe en el sistema de coordenadas en que el plugin la
produce y la devuelve en la misma respuesta, lista para planificar los lotes de
[`coordinates-dto.md`](coordinates-dto.md).

Estado: **v1**, implementado en `services/coord_transform/api.py` (FastAPI) y usado por
el SDK de los plugins (`pluto_sdk/transform_client.py`). Reemplaza a los tópicos
`plugin/<uuid>/coordinates/raw` y `/polar`, que ya no existen.

## 1. Dónde

`POST http://coord_transform:8000/transform`, dentro de `pluto-network`. Los plugins
reciben la base de la URL como `PLUTO_TRANSFORM_URL`.

Sin autenticación: es un cálculo sin efectos, el servicio no publica puertos y solo lo
alcanzan los contenedores de esa red. `GET /health` responde `{"status": "ok"}`.

## 2. Pedido

Un `RawCoordinatesPayload` (`services/coord_transform/models.py`):

```json
{ "type": "ENU", "coord_format": "POLAR",
  "station": { "lat": -31.4, "lon": -64.2, "alt": 400.0 },
  "coordinates": [
    { "timestamp": "2026-10-13T14:00:00Z", "az": 120.0, "el": 15.0, "range": 1500.0 }
  ] }
```

Las combinaciones de `type` y `coord_format` aceptadas son un conjunto cerrado:
`ECEF+CARTESIAN`, `ECEF+GEO`, `ECI+CARTESIAN`, `ENU+POLAR` y `ENU+CARTESIAN`. Cada punto
tiene que tener los campos de su formato: `x`, `y`, `z` en `CARTESIAN`; `lat`, `lon`,
`alt` en `GEO`; `az`, `el`, `range` en `POLAR`. Los `timestamp` son ISO 8601; sin offset
se toman como UTC.

## 3. Respuesta

`200` con un `PolarCoordinatesPayload`: la misma estación y un punto por punto recibido,
en el mismo orden.

```json
{ "station": { "lat": -31.4, "lon": -64.2, "alt": 400.0 },
  "coordinates": [
    { "timestamp": "2026-10-13T14:00:00Z", "az": 120.0, "el": 15.0, "range": 1500.0 }
  ] }
```

`az` es el azimut geográfico (desde el norte verdadero, en sentido horario) y `el` la
elevación sobre el horizonte, en grados; `range` en km. Son los ángulos de §9 de
[`coordinates-dto.md`](coordinates-dto.md).

| código | cuándo |
|---|---|
| `200` | transformado |
| `422` | JSON inválido, una combinación no aceptada, o puntos que no corresponden al formato. El cuerpo dice qué campo y por qué |

El esquema OpenAPI del servicio está en `http://coord_transform:8000/docs`.
