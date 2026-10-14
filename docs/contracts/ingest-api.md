# Contrato de la API de ingesta: `/api/`

Cómo entran al servidor los datos de los plugins y el estado de las placas, y cómo el
front descubre placas y las vincula a un plugin. Reemplaza a los tópicos
`plugin/<uuid>/data/<tipo>` y `device/<id>/status|state` como entrada al backend: la
placa sigue hablando MQTT con su plugin, y el plugin le reenvía al servidor por HTTP.

Estado: **v1**, implementado en el servidor (`server_core/api.py`, Django REST Framework)
y en los plugins a través de `plugins/_sdk/pluto_sdk/` (cliente con cola y reintentos, y
el puente de la placa). Los tópicos `plugin/<uuid>/data/<tipo>` ya no existen.

El esquema OpenAPI se sirve en `/api/schema` y su Swagger en `/api/docs`. Este documento
explica las reglas; el esquema tiene el detalle de cada campo. Los errores vienen siempre
como `{"detail": "…"}`, salvo los de validación de un campo (`{"device_id": ["…"]}`).

## 1. Dos tipos de cliente

| cliente | autenticación | endpoints |
|---|---|---|
| contenedor de un plugin | `Authorization: Plugin <token>` de su instancia (§2) | §3, §4 y §5 |
| la persona que usa PluTO, desde el front | `Authorization: Bearer <jwt>` (§6) | §7 |

Cada endpoint acepta uno solo de los dos: un token de plugin en un endpoint del front, o
un JWT en uno de plugins, no se lee y la respuesta es `401`. PluTO tiene un único usuario,
así que no hay roles ni permisos por usuario: alcanza con estar logueado.

## 2. Token por instancia

- Al lanzar un plugin, el servidor genera un token nuevo (`pluto_…`) y se lo pasa al
  contenedor como `PLUTO_API_TOKEN`, junto con `PLUTO_API_URL` (por defecto
  `http://server:8000/api/`) y `PLUTO_TRANSFORM_URL` (por defecto
  `http://coord_transform:8000/`, [`transform-api.md`](transform-api.md)). En la base solo
  queda su sha256.
- Al detenerlo, el hash se borra. Un contenedor que siga corriendo recibe `401`.
- **El token decide la instancia, y la instancia decide la placa.** Ninguna URL de §3 a §5
  lleva un `plugin_id` ni un `device_id`. Un `plugin_id` distinto dentro del envelope se
  ignora y queda en el log.
- Si la instancia tiene placa vinculada, el contenedor también recibe `ROTOR_DEVICE_ID`
  (la MAC, doce dígitos hexadecimales en minúscula, como en
  [`device-state.md`](device-state.md)).

## 3. `POST /api/plugin-data/<message_type>`

Guarda una fila de `PluginData` por envelope. `message_type` cumple `[a-z0-9_-]{1,32}` y
tiene que estar entre los que declara el tipo de plugin (`tinygs`: `tracking`, `rx`;
`file_tracker`: ninguno). La URL decide el tipo, no el envelope.

El cuerpo es un envelope (JSON) o una lista de 1 a 100 envelopes:

```json
{
  "schema_version": 1,
  "message_id": "5b0e2c1e-…",
  "device": "heltec-cba",
  "source_topic": "pluto/heltec-cba/rx",
  "received_at": "2026-10-09T14:02:11.204+00:00",
  "payload_format": "json",
  "payload": { "rssi": -112, "snr": 4.5 }
}
```

Solo llegan a la fila `device`, `payload_format`, `message_id`, `source_topic`,
`received_at`, `schema_version` y `payload`. Un `payload` que no es objeto se guarda como
`{"value": …}` con `payload_format: "coerced"`. Cada envelope puede pesar hasta 128 KiB
(el plugin trunca el payload de la placa a 64 KiB, y base64 lo agranda un tercio).

### Respuesta a un envelope

| código | cuándo | qué hace el plugin |
|---|---|---|
| `201` | guardado: `{"message_id": …, "result": "ingested"}` | sigue |
| `200` | ese `message_id` ya estaba: `"result": "duplicate"` | lo da por entregado |
| `400` | JSON inválido, `message_type` mal formado, envelope que no es objeto, o el tipo de plugin rechazó el payload | descarta y registra |
| `401` | falta el token, o no es de una instancia en ejecución | reintenta con espera larga |
| `403` | el tipo de plugin no manda ese `message_type` | descarta y registra |
| `413` | envelope de más de 128 KiB, o cuerpo de más de 2,5 MB | descarta |
| `415` | el cuerpo no es `application/json` | descarta |
| `5xx` | base caída o error inesperado | reintenta con backoff |

Un `message_id` repetido nunca duplica filas, así que reintentar es seguro.

### Respuesta a un lote

Siempre `200`, con un resultado por envelope en el mismo orden, para reintentar solo los
que fallaron:

```json
{ "results": [
  { "message_id": "a", "result": "ingested" },
  { "message_id": "b", "result": "duplicate" },
  { "message_id": null, "result": "rejected", "error": "An envelope must be a JSON object." }
] }
```

Los errores del lote entero (token, `message_type`, lista vacía o de más de 100) se
responden como en la tabla de arriba.

## 4. `POST /api/device/status` y `POST /api/device/state`

El reporte de la placa vinculada a la instancia, con el mismo cuerpo que la placa publica
en [`device-state.md`](device-state.md): `status` es el texto `online` u `offline`,
`state` el documento JSON de §3 de ese contrato. El plugin lo reenvía tal cual.

| código | cuándo |
|---|---|
| `201` | guardado: `{"device_id": …}` |
| `400` | no es un `status` o un `state` válido |
| `401` | como en §3 |
| `403` | la instancia no tiene placa vinculada |

## 5. Apuntamiento: `GET /api/plugin/rotor` y `POST /api/dispatch-orders`

Lo que necesita un plugin para apuntar su placa: el dispatcher vive en el plugin
(`plugins/_sdk/pluto_sdk/dispatcher.py`), y el backend le da los límites y guarda lo que
publica.

### `GET /api/plugin/rotor`

La placa vinculada a la instancia y sus límites de apuntamiento, o `null` si no tiene.
El plugin lo pide antes de planificar cada trayectoria, así que un cambio de límites se
aplica desde la próxima trayectoria.

```json
{ "device_id": "a1b2c3d4e5f6", "min_elevation_deg": 10.0,
  "min_azimuth_deg": 300.0, "max_azimuth_deg": 60.0 }
```

`min_azimuth_deg` y `max_azimuth_deg` son `null` los dos cuando no hay ventana de azimut.
Una ventana con el inicio mayor que el fin pasa por el norte (de 300° a 60°).

### `POST /api/dispatch-orders`

Lo que el plugin publicó en `device/<device_id>/coordinates/polar`
([`coordinates-dto.md`](coordinates-dto.md)): una orden o una lista de 1 a 100. Cada una
es una fila de `DispatchOrder` de la placa vinculada; con el `state` que reporta la placa
se mide el error de apuntamiento y la latencia.

```json
[{ "kind": "BATCH", "t0_ms": 1789763400000, "t_sent_ms": 1789763398012,
   "points": [[0, 27000, 3000], [1000, 27050, 3010]], "reason": "" },
 { "kind": "HOLD", "t0_ms": 1789763712000, "t_sent_ms": 1789763712000,
   "points": [], "reason": "limits" }]
```

- `points` son `[dt_ms, az_cdeg, el_cdeg]` con los rangos de §3.2 del DTO, hasta 16.
- Un `BATCH` lleva al menos un punto. Un `HOLD` no lleva puntos y dice por qué:
  `end` (terminó la trayectoria), `limits` (salió de los límites), `expired` (todos los
  puntos ya habían pasado) o `stopped` (se detuvo el plugin).
- `t_sent_ms` es el instante en que el plugin publicó, no en que reporta: la orden puede
  llegar a la base más tarde sin cambiar la medición de latencia.
- La lista se guarda entera o nada: una orden inválida rechaza todas, así el plugin sabe
  qué reenviar.

| código | cuándo |
|---|---|
| `201` | guardadas: `{"stored": n}` |
| `400` | una orden que no es un `BATCH` o un `HOLD` válido, o una lista vacía o de más de 100 |
| `401` | como en §3 |
| `403` | la instancia no tiene placa vinculada |

## 6. Login del front (JWT)

| endpoint | cuerpo | respuesta |
|---|---|---|
| `POST /api/auth/token` | `{"username", "password"}` | `{"access", "refresh"}` |
| `POST /api/auth/token/refresh` | `{"refresh"}` | `{"access", "refresh"}` nuevos |
| `POST /api/auth/token/blacklist` | `{"refresh"}` | `{}`: cierra la sesión |

- El `access` dura 5 minutos y va en cada request como `Authorization: Bearer <access>`.
- El `refresh` dura un día y sirve una sola vez: cada refresh entrega uno nuevo y el viejo
  queda en una lista negra. El logout lo manda a esa lista sin esperar a que venza.
- Credenciales incorrectas o un `refresh` ya usado: `401`.
- Para llamar desde un navegador en otro origen (el front en desarrollo), ese origen tiene
  que estar en `CORS_ALLOWED_ORIGINS`.

## 7. Endpoints del front

### `GET /api/boards`

Las placas registradas en la base. No consulta el broker.

```json
[
  { "device_id": "a1b2c3d4e5f6", "name": "", "online": true,
    "status_changed_at": "2026-10-12T13:40:02Z", "last_state_at": null,
    "plugins": [ { "plugin_uuid": "…", "name": "tinygs-cba", "status": "STOPPED" } ] }
]
```

`plugins` son las instancias vinculadas a esa placa; solo una puede estar en ejecución.

### `POST /api/boards/scan`

Pregunta al broker qué placas existen y devuelve la misma lista que `GET /api/boards`.
Cada placa deja su `device/<id>/status` retenido, así que el servidor se conecta, lee
esos retenidos y se desconecta (`server_core/board_scan.py`). Registra las placas nuevas
y actualiza `online` en las conocidas. Tarda menos de medio segundo; corta tras 300 ms
sin mensajes nuevos, con un máximo de 2 s.

`503` si el broker no responde. Una placa que nunca se conectó no aparece.

### `PUT /api/plugins/<plugin_uuid>/board` y `DELETE`

`PUT` con `{"device_id": "a1b2c3d4e5f6"}` vincula la placa al plugin; `DELETE` la
desvincula. Devuelven el plugin:

```json
{ "plugin_uuid": "…", "name": "tinygs-cba", "status": "STOPPED", "board": "a1b2c3d4e5f6" }
```

| código | cuándo |
|---|---|
| `200` | vinculada o desvinculada |
| `400` | `device_id` que no son doce dígitos hexadecimales en minúscula |
| `404` | no existe el plugin, o la placa no está registrada (hay que escanear antes) |
| `409` | el plugin está en ejecución (la placa le llega al lanzarlo), u otra instancia en ejecución ya maneja esa placa (RF-31.1) |
