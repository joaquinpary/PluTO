FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Built with plugins/ as the context (see orchestrator.py), so the shared
# pluto_sdk can be copied next to the plugin's own modules.
COPY file_tracker/requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY _sdk/pluto_sdk/ ./pluto_sdk/
COPY file_tracker/ .

CMD ["python", "main.py"]