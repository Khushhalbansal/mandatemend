# MandateMend — dev tasks.
#
# Unix / macOS / Git-Bash-on-Windows. On plain Windows without `make`, run the underlying
# commands directly (they are one-liners) or use the venv:  .venv\Scripts\mandatemend ...
#
# Fresh checkout, one command:   make demo

PY ?= python
VENV := .venv
BIN := $(VENV)/bin
ifeq ($(OS),Windows_NT)
	BIN := $(VENV)/Scripts
endif

.PHONY: help setup data train score demo serve test lint types check clean

help:
	@echo "setup   - create .venv and install (locked deps + package)"
	@echo "data    - regenerate the training set (frozen batch stays put)"
	@echo "train   - train the survival + uplift models"
	@echo "score   - run the frozen-batch scorecard + pytest + ruff + mypy, append to the loop log"
	@echo "demo    - setup -> data -> train -> score  (fresh-checkout smoke test)"
	@echo "serve   - operator console at http://127.0.0.1:8000"
	@echo "test / lint / types / check - the CI gate"

setup:
	$(PY) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/pip install -r requirements-lock.txt
	$(BIN)/pip install -e . --no-deps

data:
	$(BIN)/python data/generator.py

train:
	$(BIN)/mandatemend train

score:
	$(BIN)/mandatemend score

demo: setup data train
	$(BIN)/mandatemend score --fast --no-log --note "make demo"
	@echo
	@echo "OK. Now run:  make serve   (operator console)"

serve:
	$(BIN)/mandatemend serve

test:
	$(BIN)/pytest -q --cov=mandatemend --cov-report=term-missing

lint:
	$(BIN)/ruff check src data tests

types:
	$(BIN)/mypy

check: lint types test

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	rm -f data/training_set.json logs/run_batch.sqlite logs/live_audit.sqlite logs/last_live_roundtrip.json
