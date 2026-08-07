FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# uv installieren (schneller Paketmanager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Erst nur die Abhängigkeitsdatei kopieren — so bleibt der Docker-Cache
# erhalten, solange sich die Abhängigkeiten nicht ändern.
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml

COPY app ./app

EXPOSE 8000

# Der Worker startet später mit einem anderen Befehl (ab M6):
#   python -m app.jobs.scheduler
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
