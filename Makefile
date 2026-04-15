PYTHON ?= python3.10
PIPTOOLS := $(PYTHON) -m piptools

.PHONY: deps lock check-lock run

deps:
	$(PYTHON) -m pip install --upgrade pip setuptools wheel
	$(PYTHON) -m pip install -r requirements.txt

lock:
	$(PYTHON) -m pip install --upgrade pip pip-tools
	$(PIPTOOLS) compile --resolver=backtracking --output-file=requirements.txt requirements.in

check-lock:
	$(PYTHON) -m pip install --upgrade pip pip-tools
	tmpfile=$$(mktemp); \
	$(PIPTOOLS) compile --resolver=backtracking --output-file=$$tmpfile requirements.in; \
	perl -0pi -e 's|pip-compile --output-file=.*? requirements\\.in|pip-compile --output-file=requirements.txt requirements.in|' $$tmpfile; \
	diff -u requirements.txt $$tmpfile; \
	rm $$tmpfile

run:
	$(PYTHON) main.py
