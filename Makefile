PYTHON ?= python3.10
PIPTOOLS := $(PYTHON) -m piptools

.PHONY: deps lock check-lock run test

deps:
	$(PYTHON) -m pip install --upgrade pip setuptools wheel
	$(PYTHON) -m pip install -r requirements.txt

lock:
	$(PYTHON) -m pip install --upgrade pip pip-tools
	$(PIPTOOLS) compile --resolver=backtracking --output-file=requirements.txt requirements.in

check-lock:
	$(PYTHON) -m pip install --upgrade pip pip-tools
	set -eu; tmpfile=$$(mktemp); trap 'rm -f "$$tmpfile"' EXIT; \
	CUSTOM_COMPILE_COMMAND='pip-compile --output-file=requirements.txt requirements.in' $(PIPTOOLS) compile --resolver=backtracking --output-file=$$tmpfile requirements.in; \
	diff -u requirements.txt $$tmpfile

run:
	$(PYTHON) main.py

test:
	$(PYTHON) -m unittest discover -s tests -v
	$(PYTHON) -m unittest test_regex_log -v
