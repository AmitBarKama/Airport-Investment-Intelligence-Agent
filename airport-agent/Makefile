.PHONY: help etl serve test test-py test-js clean check demo ask install check-llm

# The interpreter that has the dependencies. `python3` alone resolved to the
# system Homebrew python, which has no langchain -- so `make serve` started a
# server where llm_available() was False and the keyword planner answered every
# request, with the model never called and no tokens ever spent.
PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

help:
	@echo "make etl     build data/airports.db from source data"
	@echo "make serve   run the app at http://127.0.0.1:8000"
	@echo "make demo    answer the four sample questions in the terminal"
	@echo "make ask     interactive terminal chat"
	@echo "make install    install LangChain so the model path works"
	@echo "make check-llm  one live round trip through the configured model"
	@echo "make test    run the full test suite (python + node)"
	@echo "make check   etl + tests, from scratch"

install:
	@[ -x .venv/bin/python ] || python3 -m venv .venv
	.venv/bin/python -m pip install -r requirements.txt

check-llm:
	$(PY) check_llm.py

etl:
	$(PY) -m etl.build

etl-refresh:
	$(PY) -m etl.build --refresh

serve:
	$(PY) -m api.server

demo:
	$(PY) ask.py --demo

ask:
	$(PY) ask.py

test: test-py test-js

test-py:
	$(PY) -m unittest discover -s tests -v

# Browser-side policy: voice turn-taking and conversation-list rules. Needs
# node; skipped with a notice if absent, since the Python suite is the one that
# must run everywhere.
test-js:
	@command -v node >/dev/null 2>&1 \
		&& node --test tests/test_voice_turn_taking.mjs tests/test_conversations.mjs \
				tests/test_markdown.mjs \
		|| echo "node not found — skipping browser-side tests"

check: etl test

clean:
	rm -f data/airports.db
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
