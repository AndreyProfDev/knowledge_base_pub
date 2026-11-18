# Single entry point for this repository.
#
# Every target runs on the host so the inner loop stays fast. Targeting GNU Make
# 3.81 (macOS stock), so no .RECIPEPREFIX, no $(file ...), no undefine.

SHELL := /bin/bash
UV := uv
INSTALL_VENV ?= $(HOME)/.local/share/knowledge-base-mcp
DIST_DIR ?= dist/knowledge-base-mcp
EXTRAS ?=
PYTEST_ARGS ?=
FRESH ?=
PKG ?=
MAX_FILE_LINES := 250
MAX_FUNCTION_LINES := 100

.DEFAULT_GOAL := help
.PHONY: help install-mcp dist dist-smoke kb-warmup sync lock-check test mutation mutation-gate lint fmt check kb-check file-length function-length no-monkeypatch no-os-environ no-prod-in-tests ruff typecheck complexity complexity-report coverage coverage-report

help: ## Show this help
	@echo "usage: make <target>"
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

## ------------------------------------------------------------------ host ---

kb-warmup: ## Load the warm-up dir into the store; needs the embedder key. From a dist: uvx --python 3.12 -c <dir>/constraints.txt --find-links <dir> --with knowledge-base-mcp-server --from tools-knowledge-base knowledge-base-cli warmup
	$(UV) run knowledge-base-cli warmup

dist: ## Build $(DIST_DIR): 9 wheels + constraints.txt, plus $(DIST_DIR).tar.gz
	rm -rf '$(DIST_DIR)' '$(DIST_DIR).tar.gz'
	$(UV) build --all-packages --wheel -o '$(DIST_DIR)'
	$(UV) export --frozen --no-dev --no-hashes --all-extras --package knowledge-base-mcp-server --no-emit-workspace --no-header --no-annotate -o '$(DIST_DIR)/constraints.txt'
	tar -czf '$(DIST_DIR).tar.gz' -C '$(DIST_DIR)' .
	@echo "dist dir: $(abspath $(DIST_DIR))"
	@echo "tarball:  $(abspath $(DIST_DIR)).tar.gz"

dist-smoke: ## Run the built $(DIST_DIR) through uvx outside the repo (needs PyPI); run after `make dist`
	$(UV) run python scripts/dist_smoke.py '$(DIST_DIR)'

install-mcp: ## Install the stdio server into INSTALL_VENV (non-editable, compiled; EXTRAS=qdrant|lancedb adds a store) and print the registration line
	UV_PROJECT_ENVIRONMENT='$(INSTALL_VENV)' UV_COMPILE_BYTECODE=1 $(UV) sync --frozen --no-dev --no-editable --package knowledge-base-mcp-server $(if $(EXTRAS),--extra $(EXTRAS),)
	@echo "Register it (not run here):"
	@echo "  claude mcp add --scope user knowledge_base --env MCP_TRANSPORT=stdio -- $(INSTALL_VENV)/bin/knowledge-base-mcp"

sync: ## Install the workspace into .venv (CI is set: --frozen, no silent re-resolve)
	$(UV) sync $(if $(CI),--frozen,)

lock-check: ## Fail if uv.lock is out of sync with pyproject.toml
	$(UV) lock --check

test: ## Run the test suite
	$(UV) run pytest $(PYTEST_ARGS)

mutation: ## mutmut over every package with [tool.mutmut]; fails below 100%. FRESH=1 starts over, PKG=packages/<pkg> runs one
	@# Per package, cwd = the package: mutmut puts mutants/src first on sys.path
	@# relative to the cwd, so from the root the tests would import the original.
	@# mutmut reuses mutants/ and misses .py changes in other packages: score with FRESH=1.
	@# The score line is floored to a tenth, so 99.95% never prints as "100%".
	@# Every Python package is in: one without [tool.mutmut] fails rather than drops out.
	@# The stats are removed first, as export-cicd-stats exits 0 without writing.
	@set -uo pipefail; \
	pkgs="$(PKG)"; [ -n "$$pkgs" ] || pkgs=$$(ls -d packages/*/pyproject.toml | xargs -r -n1 dirname); \
	[ -n "$${pkgs//[[:space:]]/}" ] || { echo "no packages to mutate"; exit 1; }; \
	missing=""; for pkg in $$pkgs; do \
		grep -qs '^\[tool\.mutmut\]' "$${pkg%/}/pyproject.toml" || missing+=" $${pkg%/}"; \
	done; \
	[ -z "$$missing" ] || { echo "packages without [tool.mutmut]:$$missing"; exit 1; }; \
	summary=""; below=""; \
	for pkg in $$pkgs; do \
		pkg=$${pkg%/}; \
		$(if $(filter 1,$(FRESH)),rm -rf "$$pkg/mutants";) \
		rm -f "$$pkg/mutants/mutmut-cicd-stats.json"; \
		mutmut="$(UV) run --project $(CURDIR) --directory $(CURDIR)/$$pkg mutmut"; \
		$$mutmut run && $$mutmut export-cicd-stats \
			|| { echo "$$pkg: mutmut failed"; exit 1; }; \
		stats="$$pkg/mutants/mutmut-cicd-stats.json"; \
		line=$$(jq -r --arg pkg "$$pkg" \
			'(.total - .skipped) as $$t | "\($$pkg): killed \(.killed) survived \(.survived) timeout \(.timeout) no_tests \(.no_tests) score \(if $$t > 0 then ((.killed + .timeout) * 1000 / $$t | floor) / 10 else 0 end)%"' \
			"$$stats") || exit 1; \
		echo "$$line"; summary+="$$line"$$'\n'; \
		jq -e '.total - .skipped > 0 and .killed + .timeout == .total - .skipped' "$$stats" >/dev/null \
			|| below+=" $$pkg"; \
	done; \
	printf '\n%s' "$$summary"; \
	[ -z "$$below" ] || { echo "below 100%:$$below"; exit 1; }

lint: file-length function-length no-monkeypatch no-os-environ no-prod-in-tests ## Ruff + the file-length, function-length, no-monkeypatch, no-os-environ and no-prod-in-tests rules
	$(UV) run ruff check .
	$(UV) run ruff format --check .

fmt: ## Format and apply safe fixes
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

# Make 3.81 has no --output-sync; there parallel output interleaves.
PARALLEL := -j $(if $(filter output-sync,$(.FEATURES)),--output-sync=target)

check: ## Every per-change gate, in parallel (~30 s); before merge, mutation-gate too
	@# `coverage` runs the whole suite, so `test` would only run it twice.
	@$(MAKE) $(PARALLEL) lock-check lint typecheck coverage

mutation-gate: ## The 100% mutmut gate, FRESH (~15 min); green before merge, run once per change
	@# PKG= so a PKG from the command line or env cannot narrow the gate to one package.
	@$(MAKE) mutation FRESH=1 PKG=

# Every Python package here is the knowledge base, its config or its server, so
# the knowledge-base gate is the whole gate. Kept under its old name so the CI
# job of the same name needs no rename.
kb-check: check ## Alias of check

coverage: ## Run the suite and fail if src coverage is under pyproject's fail_under
	@# Kept out of `lint` so CI can expose it as its own required status check.
	@# skip-covered so a failure names the files with gaps instead of burying
	@# them in a full listing; the run leaves .coverage for `coverage-report`.
	$(UV) run pytest --cov --cov-report=term-missing:skip-covered $(PYTEST_ARGS)

coverage-report: ## Print a Markdown table of gaps and the total; run `make coverage` first
	@# Reads the .coverage data `coverage` left behind rather than re-running the
	@# suite, so CI can gate and summarise from one execution.
	@#
	@# --skip-covered leaves only the files with something missing, plus the
	@# TOTAL row. At 100% that is the total and a "N files skipped" line.
	@$(UV) run coverage report --format=markdown --skip-covered --skip-empty

file-length: ## Fail on any source file over $(MAX_FILE_LINES) lines
	@bad=$$(find packages -name '*.py' -not -path '*/.venv/*' -not -path '*/node_modules/*' -not -path '*/mutants/*' \
		-exec awk 'END { if (FNR > $(MAX_FILE_LINES)) print FILENAME " (" FNR " lines)" }' {} \;); \
	if [ -n "$$bad" ]; then \
		echo "files over $(MAX_FILE_LINES) lines:"; echo "$$bad"; exit 1; \
	fi

function-length: ## Fail on any function over $(MAX_FUNCTION_LINES) lines
	@# PLR0915 (in `ruff`, above) proxies this via statement count, not a line
	@# count — this is the literal line count.
	@# AST-based: a function's *own* span excludes any function/class nested
	@# directly inside it, so a factory of short nested functions is judged on
	@# its own few lines, not the sum of everything it returns.
	$(UV) run python scripts/function_length.py --max-lines $(MAX_FUNCTION_LINES)

ruff: ## Fail on any ruff lint violation (the full select list in pyproject.toml)
	@# Already covered by `lint`. Split out so CI can expose it as its own
	@# required status check, with a name a reviewer can see at a glance —
	@# this is what actually gates PLC0415 (no function-scoped imports),
	@# PLW0603 (no `global`), and everything else in [tool.ruff.lint] select.
	@# Set RUFF_OUTPUT_FORMAT=github for inline PR annotations.
	$(UV) run ruff check .

typecheck: ## Fail on any basedpyright error (typeCheckingMode = "all" in pyproject.toml)
	@# Already covered by `check`. Split out so CI can expose it as its own
	@# required status check, distinct from `ruff`/`complexity`/`coverage`.
	$(UV) run basedpyright

complexity: ## Fail on any function over the mccabe limit in pyproject.toml
	@# Already covered by `lint` (and by `ruff`, above — C901 is in the same
	@# select list). Split out so CI can expose it as its own required status
	@# check with its own Markdown report. Set RUFF_OUTPUT_FORMAT=github for
	@# PR annotations.
	$(UV) run ruff check --select C901 .

complexity-report: ## Print a Markdown complexity report for the whole workspace
	@$(UV) run python scripts/complexity_report.py

no-monkeypatch: ## Fail on any monkeypatch fixture use or mock-library patches in tests
	@bad=$$(grep -rnE \
		'\bmonkeypatch\b|unittest\.mock|\bMock\(|\bMagicMock\(|@patch\(|mock\.patch\(' \
		--include='*.py' packages 2>/dev/null); \
	if [ -n "$$bad" ]; then \
		echo "monkeypatch/mock patches found — inject a fake through a real"; \
		echo "parameter instead:"; \
		echo "$$bad"; exit 1; \
	fi

no-os-environ: ## Fail on any os.environ/getenv use outside packages/config
	@bad=$$(grep -rnE \
		'os\.environ|getenv' \
		--include='*.py' packages/*/src packages/*/tests 2>/dev/null \
		| grep -v '^packages/config/'); \
	if [ -n "$$bad" ]; then \
		echo "os.environ/getenv found outside packages/config — read it off a"; \
		echo "settings field instead:"; \
		echo "$$bad"; exit 1; \
	fi

no-prod-in-tests: ## Fail on Environment.PROD or a "prod" argument anywhere under tests/
	@# TOOLS_ENV steers every lru_cache'd settings singleton in the process
	@# (e.g. the knowledge base's get_settings()), and PROD resolves ${secret:...}
	@# against real credentials. A test that reads
	@# or sets PROD is one leaked settings load away from pinning a singleton
	@# built from real config, or reaching for a token that happens to be on
	@# the developer's machine. Use the ambient TESTING value instead — a leak
	@# is then a no-op. Scoped to a code-argument context (after `,` `=` `(`
	@# `[`), not a bare substring, so a docstring explaining this rule in prose
	@# does not trip it.
	@bad=$$(grep -rnE \
		'Environment\.PROD\b|[,=(\[][[:space:]]*["'"'"'][[:space:]]*[Pp][Rr][Oo][Dd][[:space:]]*["'"'"']' \
		--include='*.py' packages/*/tests 2>/dev/null); \
	if [ -n "$$bad" ]; then \
		echo "PROD environment found in a test — use Environment.TESTING or"; \
		echo "the ambient TOOLS_ENV value instead:"; \
		echo "$$bad"; exit 1; \
	fi
