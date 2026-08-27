# BHOOSHAKTI AI — one-command operations.
#
#   make doctor    check what is installed and what is missing
#   make setup     install everything and prepare the database
#   make api       run the API        (terminal 1)
#   make web       run the dashboard  (terminal 2)
#   make test      run every test suite
#
# Works on macOS (Intel and Apple Silicon) and Linux. Windows users: use
# Docker (`docker compose up --build`) or WSL2 — see README.md.
#
# Nothing here is hardcoded to one machine: the Homebrew prefix, the Python
# binary and the PostgreSQL bin directory are all detected at run time.

SHELL := /bin/bash

# ---------------------------------------------------------------- detection

UNAME := $(shell uname -s)

# Homebrew lives in /usr/local on Intel macOS and /opt/homebrew on Apple
# Silicon. Ask brew rather than guessing.
BREW_PREFIX := $(shell brew --prefix 2>/dev/null)

# Prefer a 3.12 interpreter, then 3.11/3.13, then whatever python3 is. The
# project needs >=3.10 for modern typing syntax.
PYTHON := $(shell command -v python3.12 2>/dev/null || \
                  command -v python3.13 2>/dev/null || \
                  command -v python3.11 2>/dev/null || \
                  command -v python3 2>/dev/null)

VENV := backend/.venv
PY   := $(VENV)/bin/python

# psql may be on PATH already (Linux, Postgres.app) or tucked inside a
# versioned Homebrew keg that is not linked.
PSQL := $(shell command -v psql 2>/dev/null || \
                ls $(BREW_PREFIX)/opt/postgresql@18/bin/psql 2>/dev/null || \
                ls $(BREW_PREFIX)/opt/postgresql@17/bin/psql 2>/dev/null || \
                ls $(BREW_PREFIX)/opt/postgresql@16/bin/psql 2>/dev/null)

DB_NAME := bhooshakti
DB_USER := bhooshakti
DB_PASS := bhooshakti

.PHONY: help doctor setup venv services db seed weather train api web mobile \
        sensors test test-backend test-mobile reset clean

help: ## Show this help
	@echo "BHOOSHAKTI AI — available commands"
	@echo ""
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS=":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "First time? Run 'make doctor', then 'make setup'."

# ------------------------------------------------------------------ doctor

doctor: ## Check prerequisites and report what is missing
	@echo "BHOOSHAKTI AI — environment check"
	@echo "=================================================================="
	@echo "  OS                 : $(UNAME)"
	@echo "  Homebrew prefix    : $(if $(BREW_PREFIX),$(BREW_PREFIX),not found (fine on Linux))"
	@echo ""
	@printf "  Python (>=3.10)    : "; \
	  if [ -n "$(PYTHON)" ]; then $(PYTHON) --version; else echo "MISSING"; fi
	@printf "  psql               : "; \
	  if [ -n "$(PSQL)" ]; then echo "$(PSQL)"; else echo "MISSING — install PostgreSQL 16+ with PostGIS"; fi
	@printf "  Node.js (>=18)     : "; \
	  command -v node >/dev/null 2>&1 && node --version || echo "MISSING"
	@printf "  npm                : "; \
	  command -v npm >/dev/null 2>&1 && npm --version || echo "MISSING"
	@printf "  mosquitto broker   : "; \
	  if command -v mosquitto >/dev/null 2>&1 || ls $(BREW_PREFIX)/sbin/mosquitto >/dev/null 2>&1; \
	    then echo "installed"; else echo "MISSING (optional — MQTT demo needs it)"; fi
	@echo ""
	@printf "  PostgreSQL running : "; \
	  if [ -n "$(PSQL)" ] && $(PSQL) -d postgres -c "SELECT 1" >/dev/null 2>&1; \
	    then echo "yes"; else echo "NO — start it, then run 'make services'"; fi
	@printf "  database '$(DB_NAME)' : "; \
	  if [ -n "$(PSQL)" ] && $(PSQL) -d $(DB_NAME) -c "SELECT 1" >/dev/null 2>&1; \
	    then echo "exists"; else echo "not created yet — run 'make db'"; fi
	@printf "  PostGIS extension  : "; \
	  if [ -n "$(PSQL)" ] && $(PSQL) -d $(DB_NAME) -tAc "SELECT PostGIS_Version()" >/dev/null 2>&1; \
	    then echo "enabled"; else echo "not enabled yet"; fi
	@printf "  virtualenv         : "; \
	  if [ -x "$(PY)" ]; then echo "$(VENV)"; else echo "not created — run 'make setup'"; fi
	@printf "  trained model      : "; \
	  ls backend/ml/artifacts/*.joblib >/dev/null 2>&1 && echo "present" || echo "not trained — run 'make train'"
	@echo "=================================================================="
	@if [ -z "$(PYTHON)" ] || [ -z "$(PSQL)" ]; then \
	  echo "Something is missing. See README.md → 'Running it' for your OS,"; \
	  echo "or skip all of this and use Docker:  docker compose up --build"; \
	fi

# ------------------------------------------------------------------- setup

setup: venv services db seed train ## Install everything and prepare the database
	@cd web && npm install --silent
	@cd mobile && npm install --silent
	@echo ""
	@echo "Ready. Open two terminals:  'make api'  and  'make web'"
	@echo "Then browse to http://localhost:5173"

venv: ## Create the Python virtualenv and install backend requirements
	@if [ -z "$(PYTHON)" ]; then \
	  echo "No Python 3 found. Install Python 3.12, then re-run."; exit 1; fi
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	@$(PY) -m pip install -q --upgrade pip
	@$(PY) -m pip install -q -r backend/requirements.txt
	@test -f .env || cp .env.example .env
	@echo "virtualenv ready ($$($(PY) --version))"

services: ## Start PostgreSQL and Mosquitto (macOS/Homebrew or systemd)
ifeq ($(UNAME),Darwin)
	@brew services start postgresql@18 >/dev/null 2>&1 || \
	 brew services start postgresql@17 >/dev/null 2>&1 || \
	 brew services start postgresql@16 >/dev/null 2>&1 || true
	@brew services start mosquitto >/dev/null 2>&1 || true
	@sleep 2
else
	@sudo systemctl start postgresql 2>/dev/null || \
	  echo "Start PostgreSQL yourself, then re-run."
	@sudo systemctl start mosquitto 2>/dev/null || \
	  echo "Mosquitto not started (optional — needed for the MQTT demo)."
endif
	@echo "services requested"

db: ## Create the database, role and PostGIS extension
	@if [ -z "$(PSQL)" ]; then echo "psql not found — install PostgreSQL 16+."; exit 1; fi
	@$(PSQL) -d postgres -tc "SELECT 1 FROM pg_roles WHERE rolname='$(DB_USER)'" | grep -q 1 || \
	  $(PSQL) -d postgres -c "CREATE ROLE $(DB_USER) WITH LOGIN PASSWORD '$(DB_PASS)' SUPERUSER"
	@$(PSQL) -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='$(DB_NAME)'" | grep -q 1 || \
	  $(PSQL) -d postgres -c "CREATE DATABASE $(DB_NAME) OWNER $(DB_USER)"
	@$(PSQL) -d $(DB_NAME) -c "CREATE EXTENSION IF NOT EXISTS postgis" >/dev/null
	@echo "database '$(DB_NAME)' ready with PostGIS"

# -------------------------------------------------------------------- data

seed: ## Rebuild the schema and load data (fetches real weather)
	@cd backend && .venv/bin/python scripts/seed.py --reset

weather: ## Refresh the cached Open-Meteo weather
	@cd backend && .venv/bin/python scripts/fetch_weather.py

train: ## Train the susceptibility model
	@cd backend && .venv/bin/python scripts/train.py

reset: seed train ## Rebuild data and model from scratch

# ------------------------------------------------------------------- run

api: ## Run the API on :8000
	@cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000

web: ## Run the dashboard on :5173
	@cd web && npm run dev

mobile: ## Run the Expo field app on :8081
	@cd mobile && npx expo start --web --port 8081

sensors: ## Run the simulated sensor network (NOT during the scripted demo)
	@cd backend && .venv/bin/python scripts/sensor_simulator.py --interval 5

# ------------------------------------------------------------------ tests

test: test-backend test-mobile ## Run every test suite

test-backend: ## Fusion, PostGIS spatial and weather tests
	@cd backend && .venv/bin/python -m pytest -q

test-mobile: ## Offline sync queue tests
	@cd mobile && npx vitest run

# ------------------------------------------------------------------ clean

clean: ## Remove virtualenvs, builds and trained model
	@rm -rf $(VENV) backend/ml/artifacts/*.joblib backend/ml/artifacts/*.json
	@rm -rf web/node_modules web/dist mobile/node_modules
	@echo "cleaned"
