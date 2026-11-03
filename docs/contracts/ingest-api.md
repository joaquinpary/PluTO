# Contrato de la API de ingesta: `/api/`

Cómo entran al servidor los datos de los plugins y el estado de las placas, y qué API usa
el front (§6 y §7). Reemplaza a los tópicos `plugin/<uuid>/data/<tipo>` y
`device/<id>/status|state` como entrada al backend: la placa sigue hablando MQTT con su
plugin, y el plugin le reenvía al servidor por HTTP.

Estado: **v1**, implementado en el servidor (`server_core/api*.py`, Django REST Framework)
y en los plugins a través de `plugins/_sdk/pluto_sdk/` (cliente con cola y reintentos, y
el puente de la placa). Los tópicos `plugin/<uuid>/data/<tipo>` ya no existen.

El esquema OpenAPI se sirve en `/api/schema` y su Swagger en `/api/docs`. Este documento
explica las reglas; el esquema tiene el detalle de cada campo. Los errores vienen siempre
como `{"detail": "…"}`, salvo los de validación de un campo (`{"device_id": ["…"]}`).

## 1. Dos tipos de cliente

| cliente | autenticación | endpoints |
|---|---|---|
| contenedor de un plugin | `Authorization: Plugin <token>` de su instancia (§2) | §3, §4 y §5 |
| la persona que usa PluTO, desde el front | `Authorization: Bearer <jwt>` (§6) | §6 y §7 |

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

## 6. Sesión del front (JWT)

| endpoint | cuerpo | respuesta |
|---|---|---|
| `GET /api/setup` | — | `{"needs_setup": bool}`: si todavía no hay usuario |
| `POST /api/setup` | `{"username", "password"}` | `201` `{"username"}`: crea el único usuario |
| `POST /api/auth/token` | `{"username", "password"}` | `{"access", "refresh"}` |
| `POST /api/auth/token/refresh` | `{"refresh"}` | `{"access", "refresh"}` nuevos |
| `POST /api/auth/token/blacklist` | `{"refresh"}` | `{}`: cierra la sesión |
| `POST /api/auth/password` | `{"current_password", "new_password"}` | `{"access", "refresh"}`: cambia la contraseña y cierra las demás sesiones |

- `GET` y `POST /api/setup` no piden login: son lo primero que ve una instalación nueva.
  `POST` solo funciona mientras no exista ningún usuario (`409` si ya hay uno) y valida la
  contraseña con los validadores de Django (`400` por campo). `manage.py createsuperuser`
  sigue siendo la forma de volver a entrar si se pierde la contraseña.
- El `access` dura 5 minutos y va en cada request como `Authorization: Bearer <access>`.
- El `refresh` dura un día y sirve una sola vez: cada refresh entrega uno nuevo y el viejo
  queda en una lista negra. El logout lo manda a esa lista sin esperar a que venza.
- Credenciales incorrectas o un `refresh` ya usado: `401`.
- Cambiar la contraseña pide la actual: `400` si no coincide o si la nueva no pasa los
  validadores. Manda a la lista negra todos los `refresh` del usuario (el de un celular
  perdido, por ejemplo) y responde un par nuevo para la sesión que la cambió.
- Para llamar desde un navegador en otro origen, ese origen tiene que estar en
  `CORS_ALLOWED_ORIGINS`. El front no lo necesita: en producción lo sirve nginx en el mismo
  origen que la API, y en desarrollo Vite le hace de proxy.

## 7. Endpoints del front

Todos piden `Authorization: Bearer <jwt>`, salvo `GET /api/health` y los de `/api/setup`
(§6). Las fechas van en UTC, en ISO 8601.

### 7.1 `GET /api/health`

Sin login. `200` si la base responde y `503` si no. Es el healthcheck del servidor; antes
estaba en `/`.

### 7.2 Instancias de plugins

| endpoint | qué hace | códigos |
|---|---|---|
| `GET /api/plugin-types` | los tipos de plugin, con `label`, `message_types` y `config_fields` | `200` |
| `GET /api/plugins` | las instancias; filtros `type`, `status` y `search` (por nombre) | `200` |
| `POST /api/plugins` | alta con `name`, `plugin_type` y `config`; queda en `STOPPED`, con los defaults del tipo en `config` | `201`; `400` |
| `GET /api/plugins/<plugin_uuid>` | una instancia | `200`; `404` |
| `PATCH /api/plugins/<plugin_uuid>` | cambia `name` y `config` | `200`; `400`; `404` |
| `DELETE /api/plugins/<plugin_uuid>` | la detiene y la borra | `204`; `404`; `409`; `502` |
| `POST /api/plugins/<plugin_uuid>/launch` | la lanza | `200`; `400`; `409`; `502` |
| `POST /api/plugins/<plugin_uuid>/stop` | la detiene | `200`; `502` |
| `POST /api/plugins/<plugin_uuid>/sync` | ajusta `status` a lo que dice Docker | `200`; `502` |
| `POST /api/plugins/<plugin_uuid>/coordinates-file` | le manda el archivo de coordenadas | `200`; `400`; `404`; `503` |
| `GET /api/plugins/<plugin_uuid>/logs?tail=N` | las últimas N líneas de su contenedor | `200`; `400`; `404`; `502` |
| `PUT` y `DELETE /api/plugins/<plugin_uuid>/board` | vincula o desvincula la placa (abajo) | ver abajo |

- **Campos por tipo.** Cada tipo declara sus campos en `config_fields` (nombre, tipo, si es
  obligatorio, default, rango, opciones, patrón). La API valida `config` contra ellos al
  guardar y responde `400` por campo; las reglas que cruzan campos (por ejemplo, las
  combinaciones válidas de `coord_type` y `coord_format` de `file_tracker`) se validan al
  guardar y al lanzar.
- **El tipo queda fijo.** `plugin_type` se elige en el alta y no cambia después: en un
  `PATCH` se ignora, igual que `status`.
- **Avisos.** La respuesta trae `warnings`: problemas que no impiden guardar, como un
  `min_elevation_deg` de tinygs más bajo que el de su placa, con el que la pasada entera se
  descarta.
- **Estado en Docker.** `docker_status` sale de una sola consulta a Docker para todo el
  listado.
- **Lanzar** genera el token de la instancia (§2) y le pasa al contenedor la ubicación de su
  placa. La primera vez construye la imagen y puede tardar minutos, así que es una request
  larga: gunicorn y nginx esperan hasta 600 s. `400` si la configuración no es válida;
  `409` si ya está corriendo o si otra instancia en ejecución maneja su placa (RF-31.1).
- **Detener** funciona también desde `ERROR` y revoca el token.
- **Borrar** detiene la instancia y la borra. `409` si ya produjo datos (`PluginData` u
  órdenes enviadas): el historial no puede quedar apuntando a una instancia que no existe,
  así que en ese caso se la detiene en lugar de borrarla.
- **Archivo de coordenadas.** Solo para `file_tracker`: multipart, con el archivo en el
  campo `file`, hasta 1 MiB y en texto UTF-8. Se publica retenido para el plugin, esté
  corriendo o no. `503` si el broker no responde: el archivo no se mandó.
- **Logs.** `tail` va de 1 a 1000, 100 por defecto. `404` si la instancia no tiene
  contenedor (al detenerla, su contenedor se borra). Un error de Docker al buscar el
  contenedor también responde `404`, y queda en el log del server.
- **Docker.** Si Docker no responde o falla al lanzar, detener, sincronizar o borrar, la
  respuesta es `502` con lo que dijo Docker en `detail`. Los logs sin Docker también dan
  `502`.

#### `PUT /api/plugins/<plugin_uuid>/board` y `DELETE`

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

### 7.3 Placas

#### `GET /api/boards`

Las placas registradas en la base. No consulta el broker.

```json
[
  { "device_id": "a1b2c3d4e5f6", "name": "", "online": true,
    "status_changed_at": "2026-10-12T13:40:02Z", "last_state_at": null,
    "plugins": [ { "plugin_uuid": "…", "name": "tinygs-cba", "status": "STOPPED" } ] }
]
```

`plugins` son las instancias vinculadas a esa placa; solo una puede estar en ejecución.

#### `POST /api/boards/scan`

Pregunta al broker qué placas existen y devuelve la misma lista que `GET /api/boards`.
Cada placa deja su `device/<id>/status` retenido, así que el servidor se conecta, lee
esos retenidos y se desconecta (`server_core/board_scan.py`). Registra las placas nuevas
y actualiza `online` en las conocidas. Tarda menos de medio segundo; corta tras 300 ms
sin mensajes nuevos, con un máximo de 2 s.

`503` si el broker no responde. Una placa que nunca se conectó no aparece.

#### Detalle, en vivo y traza

| endpoint | qué hace | códigos |
|---|---|---|
| `GET /api/boards/<device_id>` | la placa, con su ubicación y sus límites | `200`; `404` |
| `PATCH /api/boards/<device_id>` | cambia nombre, ubicación y límites | `200`; `400`; `404` |
| `GET /api/boards/live` | por placa: el último estado, la instancia en ejecución, el satélite que sigue y el motivo del último HOLD | `200` |
| `GET /api/boards/<device_id>/track` | los puntos de la pasada en curso | `200`; `404` |

- **Ubicación.** `latitude_deg` (−90 a 90), `longitude_deg` (−180 a 180) y `altitude_m`,
  opcionales. Es la de la placa, no la de la instancia: el contenedor de una instancia la
  recibe al lanzarse.
- **Límites.** Las mismas reglas que `Rotor.clean()`: la ventana de azimut lleva los dos
  extremos o ninguno (`400` con uno solo), y puede cruzar el norte (300 → 60).
- **En vivo.** `GET /api/boards/live` es para consultarlo cada segundo. `state` es `null`
  en una placa que todavía no mandó ningún estado. `meas` y `err_cdeg` vienen del documento
  de la placa ([`device-state.md`](device-state.md)) y son `null` si no los trae. El
  satélite sale del último dato `tracking` de la instancia en ejecución.
- **Traza.** Los puntos de las órdenes enviadas desde el último HOLD de la placa: vacía si
  no hay una pasada en curso.

### 7.4 Historial

| endpoint | filtros | por fecha de |
|---|---|---|
| `GET /api/boards/<device_id>/states` | `from`, `to` | `received_at` |
| `GET /api/orders` | `board`, `kind` (`BATCH`, `HOLD`), `reason` (`end`, `limits`, `expired`, `stopped`), `from`, `to` | `created_at` |
| `GET /api/plugin-data` | `plugin` (uuid), `type` (`message_type`), `from`, `to` | `created_at` |

- `GET /api/orders` muestra las órdenes que los plugins reportan con `POST /api/dispatch-orders`
  (§5).
- **Rango.** `from` entra y `to` no: `[from, to)`. `400` por campo si una fecha no se puede
  leer o si `to` no es posterior a `from`; también con un filtro inválido.
- **Paginación por cursor**, de lo más nuevo a lo más viejo: `{"next", "previous",
  "results"}`, donde `next` y `previous` son URLs completas o `null`. 100 filas por página;
  `page_size` llega hasta 1000. Las tablas crecen una fila por segundo mientras una placa
  sigue una pasada, y el cursor hace que cada página sea una consulta corta sobre el índice
  de la fecha.
- **CSV.** `?format=csv` devuelve las mismas filas como CSV, pero **todas las del rango**,
  de la más vieja a la más nueva, sin paginar y como descarga (`Content-Disposition:
  attachment`). Un valor anidado (el `payload`) va como JSON dentro de su celda.
  Pide `from` y `to`, con 7 días como máximo (`400` con `detail` si no): el archivo se
  arma entero antes de mandarlo, y una semana a un estado por segundo tarda unos minutos.
- **Columnas sacadas del payload.** `err_cdeg` en los estados, y `rssi`, `snr`,
  `crc_error` y `satellite` en los datos de plugins, con los nombres que manda el fork de
  tinyGS. `satellite` es `{"name", "norad"}`, como en `GET /api/boards/live`. Si el payload
  no los trae, o trae otra cosa, quedan en `null`, sin error; el payload completo sigue en
  la fila.
- `board` y `plugin` en las filas son el `device_id` y el `plugin_uuid`.

#### `GET /api/boards/<device_id>/states/series`

La posición comandada en el tiempo, para un gráfico: `{"points": [{"t", "az_cdeg",
"el_cdeg"}]}`. `from` y `to` son obligatorios. El rango se parte en `max_points`
intervalos iguales (por defecto 2000, hasta 10 000) y queda el último estado de cada uno,
así que nunca vienen más de `max_points` puntos, y un hueco en los datos sigue siendo un
hueco.

### 7.5 Resultados

| endpoint | parámetros | respuesta |
|---|---|---|
| `GET /api/results/pointing-error` | `board`, `from`, `to` | `{"passes": [{"start", "end", "source", "samples", "mean_err_cdeg", "max_err_cdeg"}]}` |
| `GET /api/results/reception` | `plugin`, `from`, `to` | `{"days": [{"date", "packets", "crc_errors", "rssi_mean", "snr_mean"}]}` |

Los tres parámetros son obligatorios (`400` por campo si falta alguno); una placa o una
instancia que no existe es `404`. `?format=csv` devuelve lo mismo como CSV, como descarga:
una línea por pasada (`pointing-error.csv`) o por día (`reception.csv`).

**Error de apuntamiento por pasada.**

- Una pasada es la secuencia de órdenes `BATCH` de la placa hasta el `HOLD` que la terminó,
  contando las órdenes enviadas dentro del rango. Una pasada sin su `HOLD` en el rango (en
  curso, o cortada por `to`) no entra; una que empezó antes de `from` entra desde `from`; y
  un `HOLD` sin batches antes (una trayectoria que ya había vencido) no es una pasada.
- `start` es el instante del primer punto de la pasada y `end`, el de su `HOLD`. Los
  estados de la placa entre los dos son las muestras.
- Con encoders (`source: "meas"`), el error de cada muestra es el `err_cdeg` que calculó la
  placa contra su objetivo ([`device-state.md`](device-state.md) §4.2).
- Sin encoders (`source: "commanded"`), cada estado se cruza con la orden que estaba
  ejecutando, que es la del `batch.t_sent_ms` de su documento (solo si la placa la aceptó).
  El objetivo es el punto de esa orden en el instante del estado, interpolado como lo hace
  la placa ([`coordinates-dto.md`](coordinates-dto.md) §6.7), y el error es el ángulo en el
  cielo entre ese objetivo y la posición reportada (`az_cdeg`, `el_cdeg`), con la misma
  fórmula de §4.2.
- `samples` es cuántas muestras entraron; `mean_err_cdeg` (con un decimal) y
  `max_err_cdeg` son `null` si no hubo ninguna.

**Recepción por día.** Los datos `rx` de la instancia agrupados por día UTC de llegada al
servidor: cuántos paquetes, cuántos con `crc_error` y la media de `rssi` y `snr` de los
que los traen (`null` si ninguno). Están todos los días del rango, también los que no
tuvieron paquetes, para poder comparar dos períodos.

### 7.6 `GET /api/logs/<service>?tail=N`

Las últimas N líneas de un servicio de PluTO: `server` o `coord_transform`. Responde `{"source", "lines"}`, igual que los logs de una instancia
(§7.2). `tail` va de 1 a 1000, 100 por defecto.

| código | cuándo |
|---|---|
| `200` | las líneas |
| `400` | `tail` fuera de 1 a 1000 |
| `404` | un servicio que no es ninguno de los dos, o que no tiene contenedor |
| `502` | Docker no responde |

Se leen por el proxy de Docker (`GET /containers/<id>/logs`), que lo permite con
`CONTAINERS=1`. El contenedor se busca por la etiqueta que le pone docker compose, así que
el nombre del proyecto no importa, y se leen también los detenidos: los logs de un servicio
que se cayó son los que más interesan.
