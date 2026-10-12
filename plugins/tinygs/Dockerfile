FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# skyfield pulls numpy and sgp4. They ship wheels for this image today, but a
# plugin image is built lazily on its first launch from the admin, which is a
# bad moment to discover one needs compiling. Same precaution as coord_transform.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

# Built with plugins/ as the context (see orchestrator.py), so the shared
# pluto_sdk can be copied next to the plugin's own modules.
COPY tinygs/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY _sdk/pluto_sdk/ ./pluto_sdk/
COPY tinygs/ .

CMD ["python", "main.py"]
