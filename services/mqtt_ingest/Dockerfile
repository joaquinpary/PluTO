FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# No build-essential here: paho-mqtt, mongoengine and pymongo all ship wheels,
# unlike coord_transform which needs a compiler for numpy/skyfield.
COPY requirements.txt ./

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . ./

CMD ["python", "main.py"]
