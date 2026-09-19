# Contrato de estado: `device/<device_id>/state` y `device/<device_id>/status`

Lo que la placa le informa al servidor. Es el canal de vuelta de
[`coordinates-dto.md`](coordinates-dto.md). Sin él, el servidor no sabe si la placa
aceptó una trayectoria, si tiene el reloj sincronizado ni cuánto tardan los mensajes en
llegar.

Estado: **v1**, implementado en los dos lados y probado contra una placa real (§8).

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
- La placa usa un *keepalive* de 15 s. El broker publica el *last will* después de 1,5
  keepalives sin tráfico, así que una placa caída figura `offline` en unos 20 s como
  máximo. En la prueba de §8 tardó 16 s.

Es la misma convención que usa el fork de tinyGS para las estaciones, así el servidor
trata igual a las dos placas.

## 3. `state`: qué está haciendo la placa

Va en JSON y no en binario como las coordenadas, por estas razones:

- no es el camino de control, así que no aplica el tope de 64 bytes de RNF-19.1;
- se lee directo con `mosquitto_sub`;
- el dashboard lo puede consumir por MQTT sobre WebSockets sin decodificar nada;
- el esquema es fijo (números y palabras conocidas), así que la placa lo arma con
  `snprintf`, sin parser, sin heap y sin sumar dependencias.

**Cuándo se publica:**

- cada 1 s mientras ejecuta una trayectoria y cada 10 s en reposo (valores de partida);
- además, inmediatamente al aceptar o rechazar un batch, para que el servidor se entere
  sin esperar al próximo ciclo;
- y apenas cambia `mode`, por ejemplo cuando termina una pasada y pasa de `tracking` a
  `holding`. Si no, el dashboard mostraría "siguiendo" hasta 10 s después de que la
  antena se detuvo.

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
| `pan_mode` | string \| null | `normal` o `flipped`: el modo en que está el pan-tilt ([`coordinates-dto.md`](coordinates-dto.md) §9). `null` si todavía no se movió. |
| `batch` | objeto \| null | el último batch recibido. `null` si no llegó ninguno. |
| `batch.t_sent_ms` | int \| null | copiado del header del batch. `null` si el header no se pudo decodificar (`bad_length`, `bad_magic`, etc.). |
| `batch.received_ms` | int | hora de la placa al recibirlo. |
| `batch.latency_ms` | int \| null | `received_ms − t_sent_ms`: la medición de RNF-01.2 (≤ 500 ms). `null` si el reloj no está sincronizado o no hay header. Incluye el desfase entre los relojes de la placa y del servidor, de algunas decenas de ms con NTP; por eso puede dar levemente negativa. |
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

- `mqtt_ingest` (el mismo proceso que guarda los datos de los plugins) se suscribe a
  `device/+/status` y `device/+/state`.
- La primera vez que una placa reporta, crea su `Rotor`, sin alta manual. `status`
  actualiza `online`, y como el mensaje es retenido y se repite en cada reconexión de la
  ingesta, solo un cambio real mueve la fecha del cambio.
- Cada `state` es una fila de `RotorState`, con los campos de §3 en columnas y además el
  documento completo, para no perder campos que se agreguen después. La hora de la placa
  se guarda solo si su reloj estaba sincronizado.
- Con las órdenes enviadas y las posiciones reportadas se puede calcular el error de
  apuntamiento.
- El dashboard puede suscribirse directo a estos tópicos por WebSockets para mostrar la
  posición en vivo, sin consultar la base.

## 7. Pendiente

- Los tiempos definitivos de publicación: 1 s y 10 s son un punto de partida.
- Con un sensor de posición, §4 pasa a reportar la medición real.

## 8. Prueba contra una placa real (2026-09-19)

Una ESP32-D0WD-V3 con este firmware, conectada por WiFi a un Mosquitto con PluTO completo
(Postgres e ingesta):

- Una pasada de 20 s, de az 300° a 60° cruzando el norte, mandada en 9 batches solapados
  con el encoder del servidor. Resultados:
  - los 9 batches aceptados;
  - latencia de transporte de 15 a 141 ms;
  - cambio de modo `flipped` → `normal` al cruzar el norte;
  - el azimut avanzó por el camino corto;
  - `holding` en el último punto, informado en el mismo instante en que terminó la
    pasada.
- Un mensaje por cada motivo de rechazo de §5: los 8 se rechazaron con su código y
  `rejected_total` subió de a uno.
- Un `HOLD` a mitad de trayectoria dejó la antena a mitad de camino y no se volvió a mover.
- La placa en reset por el pin EN, sin despedirse del broker: `offline` a los 16 s, la
  base la marcó offline, y al soltarla volvió `online` sola en 15 s.
