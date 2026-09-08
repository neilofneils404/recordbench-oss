PYTHON ?= .venv/bin/python
SYSTEM_PYTHON ?= python3.12
.DEFAULT_GOAL := test

.PHONY: bootstrap check compile compose-check publication-check test test-transcription

bootstrap:
	"$(SYSTEM_PYTHON)" scripts/bootstrap-dev.py

test:
	"$(PYTHON)" -m pytest -q

test-transcription:
	PYTHONPATH=services/transcription/src "$(PYTHON)" -c 'import os, pytest; os.chdir("services/transcription"); raise SystemExit(pytest.main(["-q"]))'

compile:
	"$(PYTHON)" -m compileall -q src scripts tests services/transcription/src services/transcription/tests

compose-check:
	./scripts/compose-check.sh

publication-check:
	"$(PYTHON)" scripts/publication-check.py

check: compile compose-check publication-check test test-transcription
