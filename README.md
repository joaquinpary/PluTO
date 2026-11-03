# PluTO
PLUgin-based Tracking Orchestrator

## Levantar PluTO

```bash
cp .env.example .env     # cambiar SECRET_KEY y las contraseñas
docker compose up -d --build
```

- El front queda en `http://localhost`. Desde otro equipo de la LAN, como el celular, se
  entra por `http://<IP de esta PC>`. Si el puerto 80 está ocupado, poné otro en `.env`
  (`PLUTO_WEB_PORT=8080`) y entrá por `http://localhost:8080`.
- La API va por el mismo puerto, bajo `/api/`. El Swagger está en `/api/docs`.
- Django (gunicorn) escucha además en `127.0.0.1:8000`, solo para esta PC: ahí apunta
  `npm run dev`. gunicorn no recarga solo: después de cambiar código de Python, corré
  `docker compose restart server`.

## Estructura

| Carpeta | Qué hay |
|---|---|
| `backend/` | Django: `pluto/` (settings y URLs), `server_core/` (modelos, `api/` con un módulo por recurso, `tests/`) y `manage.py`. Los comandos de Django se corren desde acá |
| `frontend/` | El front en React + TypeScript. `src/features/` tiene una carpeta por funcionalidad (página, componentes, lógica, hooks de la API y sus tests) y `src/shared/` lo común: el cliente de la API, la sesión, el layout y los formatos |
| `plugins/` | Los plugins (`file_tracker`, `tinygs`) y su SDK. El server construye sus imágenes desde acá |
| `services/` | `coord_transform` |
| `mosquitto/` | La configuración del broker |
| `docs/contracts/` | Los contratos entre el server, los plugins y las placas |

## Prueba de punta a punta

`frontend/e2e/smoke.e2e.ts` usa Playwright para recorrer el primer arranque contra el
stack entero:

1. crea el usuario, que entra solo, y ve el Inicio;
2. cierra la sesión y vuelve a entrar;
3. da de alta una instancia `file_tracker` y abre su detalle;
4. busca placas, y encuentra una placa simulada con un estado retenido en Mosquitto;
5. le vincula esa placa a la instancia.

No corre en el CI porque necesita todos los servicios de `docker compose`.

**Borra la base local.** La prueba arranca con la base vacía, porque `/setup` solo crea el
usuario mientras no hay ninguno. Si tenés datos que te importan, guardalos antes:

```bash
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > ~/pluto-backup.sql
```

Una vez por máquina, en `frontend/`:

```bash
npm ci
npx playwright install chromium   # si faltan bibliotecas: sudo npx playwright install-deps chromium
```

Cada corrida, desde la raíz del repo. La primera línea borra los contenedores de las instancias
que hayan quedado: están en `pluto-network`, y con alguno ahí `down` no puede borrar la red.

```bash
docker ps -aq --filter network=pluto-network --filter name=plugin- | xargs -r docker rm -f
docker compose down -v
docker compose up -d --build
cd frontend && npm run e2e
```

Si el front no está en el 80 (`PLUTO_WEB_PORT`), pasá la URL:
`E2E_BASE_URL=http://localhost:8080 npm run e2e`. Cuando falla,
`npx playwright show-trace test-results/*/trace.zip` muestra cada paso.

Para volver a tus datos:

```bash
docker ps -aq --filter network=pluto-network --filter name=plugin- | xargs -r docker rm -f
docker compose down -v
docker compose up -d --wait postgres
docker compose exec -T postgres sh -c 'psql -q -U "$POSTGRES_USER" "$POSTGRES_DB"' < ~/pluto-backup.sql
docker compose up -d
```
