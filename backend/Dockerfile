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
# Alembic gehört mit ins Bild: Beim Deployment muss `alembic upgrade head`
# im Container laufen können, sonst fehlt dem frischen Server das Schema.
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts

EXPOSE 8000

# Zwei Prozesse aus DEMSELBEN Bild — der Hoster startet sie als getrennte
# Dienste und überschreibt dafür den Befehl:
#
#   API     (dieser Standard):  uvicorn app.main:app --host 0.0.0.0 --port 8000
#   Worker  (überschreiben):    python -m app.jobs.worker
#
# **Genau eine Worker-Instanz.** Zwei würden dieselben Alarme doppelt prüfen;
# der Grund steht in CLAUDE.md unter der APScheduler-Entscheidung.
#
# Readiness-Probe des Hosters auf **/health/ready** stellen, nicht auf
# /health — letzteres antwortet absichtlich immer mit 200.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
