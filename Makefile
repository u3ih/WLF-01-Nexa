# Nexa (WLF-01) — common tasks.
SHELL := /bin/bash
PY := backend/.venv/bin/python

.PHONY: help setup seed migrate import-dataset dev run test smoke build deploy deploy-down deploy-logs purge stop

help:
	@echo "make setup       install deps, start Postgres, create DB, migrate, import data"
	@echo "make dev         run backend (reload) + frontend on :8000 / :3000"
	@echo "make run         run both in production mode"
	@echo "make seed        regenerate the sample dataset and answer key"
	@echo "make migrate     apply versioned Postgres migrations"
	@echo "make import-dataset  import dataset/*.csv into Postgres"
	@echo "make test        run the test suite (engine, guardrails, dedupe, masking)"
	@echo "make smoke       curl the running stack and check the safety rules"
	@echo "make deploy      build and run everything in Docker"
	@echo "make purge       delete sample data, outbox, logs and database state"

setup:
	./scripts/setup.sh

seed:
	cd backend && ../$(PY) -m data.generate

migrate:
	./scripts/migrate.sh

import-dataset: migrate
	./scripts/import_dataset.sh

dev:
	./scripts/run.sh dev

run:
	./scripts/run.sh prod

test:
	cd backend && .venv/bin/python -m pytest -q

test-llm:
	cd backend && NEXA_TEST_LLM=1 .venv/bin/python -m pytest -q -k llm

smoke:
	./scripts/smoke.sh

build:
	cd frontend && npm run build

deploy:
	./scripts/deploy.sh up

deploy-down:
	./scripts/deploy.sh down

deploy-logs:
	./scripts/deploy.sh logs

purge:
	./scripts/purge.sh

stop:
	- pkill -f "uvicorn app.main:app" || true
	- pkill -f "next-server" || true
	- docker compose down 2>/dev/null || true
