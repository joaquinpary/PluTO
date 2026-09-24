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

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
