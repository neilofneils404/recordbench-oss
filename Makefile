PYTHON ?= .venv/bin/python
SYSTEM_PYTHON ?= python3

.PHONY: bootstrap check compile compose-check publication-check test test-transcription

bootstrap:
	$(SYSTEM_PYTHON) scripts/bootstrap-dev.py

test:
	$(PYTHON) -m pytest -q

test-transcription:
	cd services/transcription && PYTHONPATH=src ../../$(PYTHON) -m pytest -q

compile:
	$(PYTHON) -m compileall -q src scripts tests services/transcription/src services/transcription/tests

compose-check:
	./scripts/compose-check.sh

publication-check:
	$(PYTHON) scripts/publication-check.py

check: compile compose-check publication-check test test-transcription
