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
