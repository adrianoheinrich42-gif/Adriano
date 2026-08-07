.PHONY: help install db-up db-down dev test lint fmt check up down clean

help:  ## Zeigt diese Hilfe
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Backend-Abhängigkeiten installieren
	cd backend && uv sync

db-up:  ## Nur Postgres starten
	docker compose up -d db

db-down:  ## Postgres stoppen
	docker compose stop db

dev:  ## API lokal mit Auto-Reload starten (Postgres muss laufen)
	cd backend && uv run uvicorn app.main:app --reload --port 8000

test:  ## Tests ausführen
	cd backend && uv run pytest -q

lint:  ## Linter + Typprüfung
	cd backend && uv run ruff check . && uv run mypy app

fmt:  ## Code formatieren
	cd backend && uv run ruff format . && uv run ruff check --fix .

check: lint test  ## Alles prüfen (vor jedem Commit)

up:  ## Postgres + API im Container starten
	docker compose up --build

down:  ## Alles stoppen
	docker compose down

clean:  ## Container UND Datenbankinhalt löschen
	docker compose down -v
