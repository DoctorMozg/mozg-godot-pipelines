.PHONY: help fmt lint types test test-godot test-browser validate hooks static check

SUITES := tests $(patsubst %/,%,$(wildcard plugins/*/tests/))
PLUGINS := $(patsubst %/,%,$(wildcard plugins/*/))
TEST_WORKERS ?= 4

help:
	@echo "Targets:"
	@echo "  fmt        Format and auto-fix Python"
	@echo "  lint       ruff check, ruff format --check and the skill lint"
	@echo "  types      mypy --strict on tools, tests and plugin sources"
	@echo "  test       pytest per suite, side by side (live_* tests excluded)"
	@echo "  test-godot pytest of the live_godot tests, which run a real Godot binary"
	@echo "  test-browser pytest of the live_browser tests, which drive headless Chrome"
	@echo "  validate   claude plugin validate --strict on the marketplace and every plugin"
	@echo "  hooks      pre-commit on tracked and new (untracked, not ignored) files"
	@echo "  static     lint + types + validate + hooks, in parallel"
	@echo "  check      static, then test"

fmt:
	ruff format .
	ruff check --fix .

lint:
	ruff check .
	ruff format --check .
	python3 tools/lint_skills.py
	python3 tools/repo_rules.py

# Each plugin is checked on its own: test and script module names repeat across plugins.
types: types/tools $(PLUGINS:%=types/%)

types/tools:
	mypy --cache-dir .mypy_cache/tools tools tests

types/plugins/%:
	@plugin=plugins/$*; [ -d "$$plugin/src" ] || exit 0; extra=; \
	for dir in scripts hooks; do \
	  find "$$plugin/$$dir" -maxdepth 1 -name '*.py' 2>/dev/null | grep -q . && extra="$$extra $$plugin/$$dir"; \
	done; \
	MYPYPATH="$$plugin/src:$$plugin/tests" mypy --cache-dir .mypy_cache/$* "$$plugin/src" "$$plugin/tests" $$extra

# One process per suite: each has its own conftest, and `from conftest import` takes the first one loaded.
test:
	$(MAKE) -j -O $(SUITES:%=test/%)

test/%:
	@[ -n "$$(find $* -name 'test_*.py' -print -quit)" ] || exit 0; \
	pytest -q -n $(TEST_WORKERS) -o cache_dir=.pytest_cache/$(subst /,_,$*) $*

test-godot: MARK = live_godot
test-browser: MARK = live_browser
test-godot test-browser:
	@for suite in $(SUITES); do \
	  [ -n "$$(find $$suite -name 'test_*.py' -print -quit)" ] || continue; \
	  pytest -q -m $(MARK) -o cache_dir=.pytest_cache/$(MARK)_$$(echo $$suite | tr / _) $$suite; \
	  status=$$?; [ $$status -eq 0 ] || [ $$status -eq 5 ] || exit 1; \
	done

validate: validate/. $(PLUGINS:%=validate/%)

validate/%:
	claude plugin validate $* --strict

# --all-files sees tracked files only; new files would skip the hooks until committed.
hooks:
	git ls-files -z --cached --others --exclude-standard | xargs -0 pre-commit run --files

static:
	$(MAKE) -j -O lint types validate hooks

check: static test
	@echo ""
	@echo "All checks passed."
