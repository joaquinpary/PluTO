FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY backend/pluto/ ./pluto/
COPY backend/server_core/ ./server_core/
# The orchestrator builds the plugin images from here, which is why the build
# context is the repo root and not backend/.
COPY plugins/ ./plugins/
COPY backend/manage.py ./

EXPOSE 8000

CMD ["gunicorn", "pluto.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--threads", "4", "--timeout", "600"]