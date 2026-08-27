# BHOOSHAKTI AI — one-command operations.
#
#   make setup     install everything and prepare the database
#   make demo      start API + dashboard (two terminals is fine too)
#   make test      run every test suite
#
# Native (Homebrew) run. For containers use: docker compose up --build

PY := backend/.venv/bin/python
PG := /usr/local/opt/postgresql@18/bin

.PHONY: help setup db venv seed train api web mobile sensors test test-backend test-mobile clean reset

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: venv db seed train ## Install deps, create the database, seed and train
	@cd web && npm install
	@cd mobile && npm install
	@echo ""
	@echo "Ready. Run 'make api' and 'make web' in two terminals."

venv: ## Create the Python venv and install backend requirements
	@test -d backend/.venv || python3.12 -m venv backend/.venv
	@$(PY) -m pip install -q --upgrade pip
	@$(PY) -m pip install -q -r backend/requirements.txt
	@test -f .env || cp .env.example .env

db: ## Create the PostGIS database and role
	@brew services start postgresql@18 >/dev/null 2>&1 || true
	@brew services start mosquitto >/dev/null 2>&1 || true
	@sleep 2
	@$(PG)/psql -d postgres -tc "SELECT 1 FROM pg_roles WHERE rolname='bhooshakti'" | grep -q 1 || \
		$(PG)/psql -d postgres -c "CREATE ROLE bhooshakti WITH LOGIN PASSWORD 'bhooshakti' SUPERUSER"
	@$(PG)/psql -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='bhooshakti'" | grep -q 1 || \
		$(PG)/psql -d postgres -c "CREATE DATABASE bhooshakti OWNER bhooshakti"
	@$(PG)/psql -d bhooshakti -c "CREATE EXTENSION IF NOT EXISTS postgis" >/dev/null

seed: ## Rebuild the schema and generate all simulated data
	@cd backend && .venv/bin/python scripts/seed.py --reset

train: ## Train the susceptibility model
	@cd backend && .venv/bin/python scripts/train.py

api: ## Run the API on :8000
	@cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000

web: ## Run the dashboard on :5173
	@cd web && npm run dev

mobile: ## Run the Expo field app
	@cd mobile && npx expo start

sensors: ## Run the simulated sensor network
	@cd backend && .venv/bin/python scripts/sensor_simulator.py --interval 5

test: test-backend test-mobile ## Run every test suite

test-backend: ## Fusion + PostGIS spatial tests
	@cd backend && .venv/bin/python -m pytest -q

test-mobile: ## Offline sync queue tests
	@cd mobile && npx vitest run

reset: ## Rebuild data from scratch (seed + train)
	@$(MAKE) seed && $(MAKE) train

clean: ## Remove build artefacts and virtualenvs
	@rm -rf backend/.venv backend/ml/artifacts/*.joblib backend/ml/artifacts/*.json
	@rm -rf web/node_modules web/dist mobile/node_modules
