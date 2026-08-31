PYTHON ?= .venv/bin/python

.PHONY: check compile compose-check publication-check test test-transcription

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
