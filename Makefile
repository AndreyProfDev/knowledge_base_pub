# Single entry point for this repository.
#
# Docker targets ship and run the knowledge base; the sync/test/lint/fmt targets
# run on the host so the inner loop stays fast. Targeting GNU Make 3.81 (macOS
# stock), so no .RECIPEPREFIX, no $(file ...), no undefine.

SHELL := /bin/bash
COMPOSE := docker compose
DOCKER := docker
UV := uv
PYTEST_ARGS ?=
FRESH ?=
PKG ?=
MAX_FILE_LINES := 250
MAX_FUNCTION_LINES := 100

.DEFAULT_GOAL := help
.PHONY: help build kb-warmup-dir serve up mcp-up kb-up shell down clean clean-guard env-check sync lock-check test mutation mutation-gate kb-worker lint fmt check kb-check file-length function-length no-monkeypatch no-os-environ no-prod-in-tests dockerignore-sync ruff typecheck complexity complexity-report coverage coverage-report ui-install ui-generate kb-openapi ui-lint ui-typecheck ui-coverage ui-package ui-audit ui-check ui-mutation ui-e2e

help: ## Show this help
	@echo "usage: make <target>"
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

env-check: ## Warn if no embedding key is configured (skipped for KB_EMBEDDER=bge-m3)
	@# A warning, not a failure: mcp-up/kb-up wait on healthchecks, so a server
	@# that exits for want of the key fails those targets loudly anyway.
	@# Compose's own resolution (.env, env_file and the shell), as kb-warmup-dir.sh reads it.
	@# jq -e exits 1 for "false" (the key is missing) and >1 when jq itself fails.
	@config=$$($(COMPOSE) config --format json) \
		|| { echo "warning: '$(COMPOSE) config' failed (above), so the embedding key was not checked."; exit 0; }; \
	status=0; \
	jq -e '.services["mcp-server"].environment | .KB_EMBEDDER == "bge-m3" or ((.OPEN_AI_API_KEY // "") != "")' \
		<<<"$$config" >/dev/null || status=$$?; \
	if [ $$status -gt 1 ]; then \
		echo "warning: jq failed (exit $$status), so the embedding key was not checked."; \
	elif [ $$status -eq 1 ] && [ ! -f .env ]; then \
		echo "warning: no .env file, so no OPEN_AI_API_KEY reaches the containers."; \
		echo "         Copy .env.example to .env, or use KB_EMBEDDER=bge-m3."; \
	elif [ $$status -eq 1 ]; then \
		echo "warning: .env sets no non-empty OPEN_AI_API_KEY."; \
		echo "         Set it in .env, or use KB_EMBEDDER=bge-m3."; \
	fi

## ---------------------------------------------------------------- docker ---

build: ## Build the knowledge-base image and the UI image
	$(COMPOSE) build

kb-warmup-dir: ## Create the KB warm-up dir (KB_WARMUP_DIR), check the KB worker can write it, else ACL it; needs docker compose, jq (setfacl on Linux if the probe fails)
	COMPOSE="$(COMPOSE)" scripts/kb-warmup-dir.sh

serve: env-check kb-warmup-dir ## Serve the MCP server on http://localhost:9799/mcp in the foreground; needs docker compose, jq (setfacl on Linux if the probe fails)
	$(COMPOSE) up mcp-server

up: env-check kb-warmup-dir ## Start everything detached: the MCP server, the KB API and UI
	$(COMPOSE) up -d --wait mcp-server
	$(COMPOSE) up -d --wait knowledge-ui

mcp-up: env-check kb-warmup-dir ## Serve only the MCP server detached; stop it with `make down`; needs docker compose, jq (setfacl on Linux if the probe fails)
	$(COMPOSE) up -d --wait mcp-server

kb-up: env-check kb-warmup-dir ## Serve the KB REST API (:8000/docs) and UI (:8081) detached; needs docker compose, jq (setfacl on Linux if the probe fails)
	$(COMPOSE) up -d --wait knowledge-ui

shell: ## Open a shell inside the image
	$(COMPOSE) run --rm --entrypoint sh mcp-server

down: ## Stop and remove containers
	$(COMPOSE) down --remove-orphans

clean: ## Stop the containers, then DELETE the volumes (every stored memory) and both built images; needs CONFIRM=delete-volumes
	@# The guard lives in the recipe, not in a permission prompt: a prompt matches
	@# one spelling (`make clean`), while `make down clean` or `make -k clean`
	@# reach this recipe all the same. No `down` prerequisite, so nothing runs
	@# before the guard; `down -v --remove-orphans` below stops everything itself.
	@# One recipe line: `make -i clean` ignores a failed line and runs the next,
	@# so the guard and the deletion must share a shell.
	@# knowledge-ui has no image: key, so compose names its build <project>-<service>.
	@# The e2e image (knowledge-base:e2e, `make ui-e2e`) is left alone.
	@# An allowlist read from the shell's own environment (make exports command-line
	@# variables), never spliced into the script: a test that errors refuses too.
	@[ "$${CONFIRM-}" = delete-volumes ] || { \
		echo "make clean deletes the volumes, i.e. every stored memory. Refusing."; \
		echo "To proceed: make clean CONFIRM=delete-volumes"; \
		exit 1; \
	}; \
	set -x; \
	$(COMPOSE) down -v --remove-orphans || exit 1; \
	$(DOCKER) image rm knowledge-base:latest knowledge_base-knowledge-ui || true

# Stand-ins print RAN instead of touching docker. A refusal must print none under
# -i -k or a quote-bearing CONFIRM; CONFIRM=delete-volumes must print it, so a
# renamed or emptied recipe fails here rather than passing vacuously.
CLEAN_PROBE := env -u CONFIRM -u MAKEFLAGS -u MAKELEVEL $(MAKE) -s -i -k --no-print-directory clean COMPOSE='echo COMPOSE-RAN' DOCKER='echo DOCKER-RAN'

clean-guard: ## Fail unless `make clean` refuses down -v without CONFIRM=delete-volumes
	@out=$$($(CLEAN_PROBE) 2>&1; $(CLEAN_PROBE) 'CONFIRM=x" "y' 2>&1); \
	if grep -q RAN <<<"$$out"; then echo "make clean reached down -v unconfirmed:"; echo "$$out"; exit 1; fi; \
	$(CLEAN_PROBE) CONFIRM=delete-volumes 2>&1 | grep -q '^COMPOSE-RAN down -v' \
		|| { echo "make clean CONFIRM=delete-volumes no longer runs down -v"; exit 1; }

## ------------------------------------------------------------------ host ---

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

kb-worker: ## Run the Knowledge Base write worker on the host (local queue + LanceDB under data/)
	TOOLS_ENV=local $(UV) run knowledge-base-worker

lint: file-length function-length no-monkeypatch no-os-environ no-prod-in-tests dockerignore-sync clean-guard ## Ruff + the file-length, function-length, no-monkeypatch, no-os-environ, no-prod-in-tests, dockerignore-sync and clean-guard rules
	$(UV) run ruff check .
	$(UV) run ruff format --check .

fmt: ## Format and apply safe fixes
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

# Make 3.81 has no --output-sync; there parallel output interleaves.
PARALLEL := -j $(if $(filter output-sync,$(.FEATURES)),--output-sync=target)

check: ## Every per-change gate, in parallel (~30 s); before merge, mutation-gate too
	@# `coverage` runs the whole suite, so `test` would only run it twice.
	@$(MAKE) $(PARALLEL) lock-check lint typecheck coverage ui-check

mutation-gate: ## Both 100% mutation gates, FRESH (~15 min); green before merge, run once per change
	@# Sequential: mutmut and Stryker each use every core.
	@# PKG= so a PKG from the command line or env cannot narrow the gate to one package.
	@$(MAKE) mutation FRESH=1 PKG=
	@$(MAKE) ui-mutation FRESH=1

# Every Python package here is the knowledge base, its config or its server, so
# the knowledge-base gate is the whole gate. Kept under its old name so the CI
# job of the same name needs no rename.
kb-check: check ## Alias of check

dockerignore-sync: ## Fail unless Dockerfile.dockerignore is .dockerignore + packages/knowledge-base-ui
	@grep -v '^#' Dockerfile.dockerignore | grep -vx 'packages/knowledge-base-ui' | diff -u .dockerignore - \
		|| { echo 'Dockerfile.dockerignore drifted from .dockerignore (diff above)'; exit 1; }
	@grep -qx 'packages/knowledge-base-ui' Dockerfile.dockerignore \
		|| { echo 'Dockerfile.dockerignore must exclude packages/knowledge-base-ui'; exit 1; }

# --ignore-scripts skips each script's `pre` hook (`generate`), which would
# otherwise rerun per script and race itself under -j; ui-generate runs it once.
# npx tools run from the package dir, as npm exec keeps cwd.
UI_DIR := packages/knowledge-base-ui
UI_NPM := npm --prefix $(UI_DIR)
UI_RUN := $(UI_NPM) run --ignore-scripts

ui-install: ## npm ci in packages/knowledge-base-ui
	$(UI_NPM) ci

ui-generate: ## Write src/api/schema.d.ts and src/routeTree.gen.ts
	$(UI_NPM) run generate

kb-openapi: ## Regenerate packages/knowledge-base-api/openapi.json
	uv run python -c "import json,sys; sys.path.insert(0,'packages/knowledge-base/tests'); from fake_kb import open_fake_kb; from tools_knowledge_base_api.app import create_app; print(json.dumps(create_app(open_fake_kb()).openapi(), indent=2))" > packages/knowledge-base-api/openapi.json

ui-lint: ui-generate ## eslint and prettier --check over the UI
	$(UI_RUN) lint

ui-typecheck: ui-generate ## tsc --noEmit over the UI
	$(UI_RUN) typecheck

ui-coverage: ui-generate ## vitest with 100% coverage over the UI's src/lib/**
	$(UI_RUN) coverage

ui-package: ui-generate ## vite build, then size-limit
	$(UI_RUN) build
	cd $(UI_DIR) && npx size-limit

ui-audit: ui-generate ## knip: unused files, exports and dependencies in the UI
	@# --no-gitignore: the generated route tree, the entry reaching every route, is gitignored.
	cd $(UI_DIR) && npx knip --no-gitignore

ui-check: ui-lint ui-typecheck ui-coverage ui-package ui-audit ## Every UI gate; needs `make ui-install`

# Stryker exits 1 below thresholds.break (100). --incremental reuses
# reports/stryker-incremental.json, blind to non-mutated src changes: scored runs use FRESH=1.
# Stryker passes a NaN score when no mutant is valid (Killed/Survived/Timeout/NoCoverage;
# CompileError, RuntimeError, Ignored and Pending are not), so the json report must hold one.
UI_MUTATION_JSON := $(UI_DIR)/reports/mutation/mutation.json
ui-mutation: ui-generate ## StrykerJS over the UI's src/lib/**, fails below 100%; FRESH=1 ignores the incremental file
	rm -f $(UI_MUTATION_JSON)
	$(UI_RUN) mutate -- --incremental $(if $(filter 1,$(FRESH)),--force)
	@jq -e '[.files[].mutants[] | select(.status | IN("Killed","Survived","Timeout","NoCoverage"))] | length > 0' \
		$(UI_MUTATION_JSON) >/dev/null \
		|| { echo "ui-mutation: no valid (Killed/Survived/Timeout/NoCoverage) mutants in $(UI_MUTATION_JSON)"; exit 1; }
	@# Stryker scores a Timeout as detected, yet an overloaded runner times out mutants that
	@# would survive; the full run has none, so any Timeout fails rather than hides one.
	@jq -e '[.files[].mutants[] | select(.status == "Timeout")] | length == 0' \
		$(UI_MUTATION_JSON) >/dev/null \
		|| { echo "ui-mutation: Timeout mutants in $(UI_MUTATION_JSON) may hide survivors; lower the load or raise timeoutMS in stryker.config.mjs"; exit 1; }

# Its own project, so its volumes start empty and `down -v` touches nothing else;
# on host ports 18000 and 18081, so it runs beside the prod stack on 8000/8081.
# `env` in front, so scripts/kb-warmup-dir.sh's word-split $COMPOSE keeps them.
UI_E2E_API_PORT := 18000
UI_E2E_UI_PORT := 18081
UI_E2E_COMPOSE := env KB_IMAGE_TAG=e2e KB_API_PORT=$(UI_E2E_API_PORT) KB_UI_PORT=$(UI_E2E_UI_PORT) $(COMPOSE) -p kb-e2e

ui-e2e: ## Playwright against a fresh kb-e2e compose stack, then down -v; needs Docker, OPEN_AI_API_KEY, jq (setfacl on Linux if the probe fails)
	cd $(UI_DIR) && npx playwright install chromium
	@# A copy: the worker dumps every item it stores into the warm-up dir.
	@set -uo pipefail; dir=$$(mktemp -d) || exit 1; trap 'rm -rf "$$dir"' EXIT; \
	cp -r $(UI_DIR)/e2e/warmup/. "$$dir" || exit 1; \
	export KB_WARMUP_DIR="$$dir"; \
	COMPOSE="$(UI_E2E_COMPOSE)" scripts/kb-warmup-dir.sh || { $(UI_E2E_COMPOSE) down -v; exit 1; }; \
	$(UI_E2E_COMPOSE) up -d --build --wait knowledge-ui || { $(UI_E2E_COMPOSE) down -v; exit 1; }; \
	KB_UI_URL=http://localhost:$(UI_E2E_UI_PORT) $(UI_NPM) run e2e; status=$$?; $(UI_E2E_COMPOSE) down -v; exit $$status

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
