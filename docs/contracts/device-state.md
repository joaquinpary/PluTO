# Contrato de estado: `device/<device_id>/state` y `device/<device_id>/status`

Lo que la placa le informa al servidor. Es el canal de vuelta de
[`coordinates-dto.md`](coordinates-dto.md). Sin él, el servidor no sabe si la placa
aceptó una trayectoria, si tiene el reloj sincronizado ni cuánto tardan los mensajes en
llegar.

Estado: **v1**, propuesto, sin implementar.

## 1. Tópicos

| tópico | dirección | formato | QoS | `retain` |
|---|---|---|---|---|
| `device/<device_id>/status` | ESP32 → servidor | texto: `online` / `offline` | 1 | **true** |
| `device/<device_id>/state` | ESP32 → servidor | JSON (§3) | 0 | false |

`device_id` es el mismo que en [`coordinates-dto.md`](coordinates-dto.md) §2: la MAC de
la interfaz station, doce dígitos hexadecimales en minúscula.

## 2. `status`: si la placa está conectada

- Al conectarse al broker, la placa publica `online` con `retain`.
- En la misma conexión registra `offline` como *last will*. Si la placa se cae sin
  despedirse (corte de luz, WiFi), el broker publica `offline` por ella.
- Con `retain`, quien se suscribe después (el dashboard, o el servidor tras un reinicio)
  ve el último estado sin esperar al próximo mensaje.

Es la misma convención que usa el fork de tinyGS para las estaciones, así el servidor
trata igual a las dos placas.

## 3. `state`: qué está haciendo la placa

Va en JSON y no en binario como las coordenadas, por estas razones:

- no es el camino de control, así que no aplica el tope de 64 bytes de RNF-19.1;
- se lee directo con `mosquitto_sub`;
- el dashboard lo puede consumir por MQTT sobre WebSockets sin decodificar nada;
- ESP-IDF ya trae cJSON (componente `json`), así que no suma dependencias.

**Cuándo se publica:**

- cada 1 s mientras ejecuta una trayectoria y cada 10 s en reposo (valores de partida);
- además, inmediatamente al aceptar o rechazar un batch, para que el servidor se entere
  sin esperar al próximo ciclo.

**Payload:**

```json
{
  "v": 1,
  "ts_ms": 1789763400123,
  "clock_synced": true,
  "mode": "tracking",
  "az_cdeg": 12345,
  "el_cdeg": 4500,
  "pan_mode": "normal",
  "batch": {
    "t_sent_ms": 1789763398000,
    "received_ms": 1789763398140,
    "latency_ms": 140,
    "accepted": true,
    "error": null
  },
  "rejected_total": 0
}
```

| campo | tipo | significado |
|---|---|---|
| `v` | int | versión de este payload: 1. Agregar campos no la cambia; el servidor ignora los que no conoce. |
| `ts_ms` | int | hora de la placa al armar el mensaje, epoch UTC en milisegundos. Si el reloj no está sincronizado igual se manda, pero no es confiable. |
| `clock_synced` | bool | lo que devuelve `sntp_manager_is_synced()`. En `false`, la placa descarta todo batch ([`coordinates-dto.md`](coordinates-dto.md) §6.4). |
| `mode` | string | `tracking` (ejecutando una trayectoria), `holding` (quieta después de un `HOLD` o del último punto) o `idle` (todavía no recibió ninguna trayectoria). |
| `az_cdeg`, `el_cdeg` | int \| null | posición en az/el geográficos, en las mismas unidades que las coordenadas (§4). `null` si todavía no se movió. |
| `pan_mode` | string | `normal` o `flipped`: el modo en que está el pan-tilt ([`coordinates-dto.md`](coordinates-dto.md) §9). |
| `batch` | objeto \| null | el último batch recibido. `null` si no llegó ninguno. |
| `batch.t_sent_ms` | int | copiado del header del batch. |
| `batch.received_ms` | int | hora de la placa al recibirlo. |
| `batch.latency_ms` | int \| null | `received_ms − t_sent_ms`: la medición de RNF-01.2 (≤ 500 ms). `null` si el reloj no está sincronizado. |
| `batch.accepted` | bool | si la placa lo aceptó. |
| `batch.error` | string \| null | el motivo del rechazo (§5). `null` si se aceptó. |
| `rejected_total` | int | batches rechazados desde el arranque. |

## 4. Qué es la "posición"

Los servos de hobby no informan dónde están, así que la placa no mide la posición real.
Lo que reporta es el último ángulo que les comandó, ya con los límites y la calibración
aplicados, convertido de vuelta a az/el geográficos.

Aun así sirve: muestra cuándo un límite recortó el movimiento, cuándo cambió el modo del
pan-tilt y cuánto se atrasa el movimiento respecto del objetivo. Lo que no mide es el
error mecánico. Si más adelante se agrega un sensor de posición (encoder o IMU), este
campo pasa a llevar la medición sin cambiar el formato.

## 5. Motivos de rechazo

Hay un código por cada regla de [`coordinates-dto.md`](coordinates-dto.md):

| `error` | regla |
|---|---|
| `bad_length` | menos de 19 bytes, o distinto de `19 + 8 * count` (§6.1) |
| `bad_magic` | `magic` desconocido (§6.1 y §5) |
| `reserved_flags` | algún bit reservado seteado (§6.1) |
| `bad_count` | `count > 16`, `0` sin `HOLD`, o puntos con `HOLD` (§6.1) |
| `out_of_range` | `az_cdeg > 35999` o `el_cdeg` fuera de ±9000 (§6.1) |
| `not_increasing` | `dt_ms` no estrictamente creciente (§6.5) |
| `all_expired` | todos los puntos vencidos (§6.3) |
| `clock_not_synced` | reloj sin sincronizar (§6.4) |
| `unreachable` | algún punto fuera del alcance del pan-tilt en los dos modos (§9) |

## 6. Cómo lo usa el servidor

Esta sección es orientativa.

- Un proceso del core con el mismo patrón que `mqtt_ingest` se suscribe a
  `device/+/status` y `device/+/state`. Guarda la presencia, las posiciones y los
  rechazos, asociados al rotor por `device_id`.
- Con las órdenes enviadas y las posiciones reportadas se calcula el error de
  apuntamiento.
- El dashboard puede suscribirse directo a estos tópicos por WebSockets para mostrar la
  posición en vivo, sin consultar la base.

## 7. Pendiente de implementar

- Firmware: armar el JSON con cJSON y configurar el *last will* en `mqtt_manager`.
- Servidor: el modelo de rotor con su `device_id` y la ingesta de estos tópicos.
- Los tiempos definitivos de publicación: 1 s y 10 s son un punto de partida.
