.PHONY: help install db-up db-down dev web test lint fmt check up down clean \
        migrate migrate-down migration migration-check db-shell

help:  ## Zeigt diese Hilfe
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Backend-Abhängigkeiten installieren
	cd backend && uv sync

db-up:  ## Nur Postgres starten
	docker compose up -d db

db-down:  ## Postgres stoppen
	docker compose stop db

db-shell:  ## psql-Konsole auf der lokalen Datenbank
	docker compose exec db psql -U flugalarm -d flugalarm

migrate:  ## Schema auf den neuesten Stand bringen
	cd backend && uv run alembic upgrade head

migrate-down:  ## Eine Migration zurücknehmen
	cd backend && uv run alembic downgrade -1

migration:  ## Neue Migration aus Modelländerungen erzeugen: make migration m="beschreibung"
	cd backend && uv run alembic revision --autogenerate -m "$(m)"

migration-check:  ## Weichen Modelle und Datenbank voneinander ab?
	cd backend && uv run alembic check

dev:  ## API lokal mit Auto-Reload starten (Postgres muss laufen)
	cd backend && uv run uvicorn app.main:app --reload --port 8000

web:  ## Web-Frontend ausliefern (http://localhost:3000)
	cd web && python3 -m http.server 3000

suche:  ## Einmalige Amadeus-Suche: make suche a="MUC BCN 2026-09-06 --rueckflug 2026-09-13"
	cd backend && uv run python -m scripts.amadeus_suche $(a)

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
