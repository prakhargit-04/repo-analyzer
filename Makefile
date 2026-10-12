# One-command developer workflow. Run `make help`.
PY ?= python
NPM ?= npm --prefix frontend

.PHONY: help setup test test-backend test-frontend check build network-tests mutation-checks clean verify

help:
	@echo "make setup          install backend + frontend dependencies"
	@echo "make test           backend (hermetic, no network) + frontend tests"
	@echo "make check          typecheck + lint (frontend) and repo hygiene"
	@echo "make build          production frontend build (needs internet for Google Fonts)"
	@echo "make verify         setup-free: backend suite twice + mutation checks + frontend tests + checks (minus build)"
	@echo "make mutation-checks  break each cache guard in a temp copy; tests must catch every one"
	@echo "make network-tests  opt-in: real clones + live Semgrep 'auto' scan"
	@echo "make clean          remove caches / build artifacts"

setup:
	$(PY) -m pip install -r requirements.txt pytest pytest-timeout pyflakes
	$(NPM) ci

test-backend:
	$(PY) -m pytest tests/ -q --timeout=120

test-frontend:
	$(NPM) test

test: test-backend test-frontend

check:
	$(PY) scripts/check_repo_hygiene.py
	$(PY) -m pyflakes pipeline/main.py pipeline/parser_interface.py pipeline/graph_builder.py
	$(NPM) run typecheck
	$(NPM) run lint

build:
	$(NPM) run build

mutation-checks:
	$(PY) scripts/run_cache_mutation_checks.py

verify:
	$(MAKE) test-backend
	$(MAKE) test-backend
	$(MAKE) mutation-checks
	$(MAKE) test-frontend
	$(MAKE) check

network-tests:
	$(PY) -m pytest tests/ -m network -q

clean:
	$(PY) scripts/check_repo_hygiene.py --clean || true
	rm -rf frontend/.next frontend/tsconfig.tsbuildinfo
