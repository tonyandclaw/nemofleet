# nemofleet — convenience targets. Scripts self-locate the repo root, so `make`
# works from anywhere in the tree.
SHELL := /bin/bash

.PHONY: help bootstrap boot health mail-up gen-certs lint test itest clean security-scan export import audit-rebaseline siem-export metrics-export

help: ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

bootstrap: ## first-time setup on a new device (certs, token, runtime config)
	bash provisioning/bootstrap.sh

boot: ## bring up the whole stack (idempotent)
	bash scripts/boot-stack.sh

health: ## zero-cost health / hygiene check
	bash scripts/healthcheck.sh

mail-up: ## configure the real SMTP relay for outbound notifications (reads .env)
	bash services/mail/up.sh

gen-certs: ## (re)generate dashboard CA + TLS + bridge token
	bash scripts/gen-dash-ca.sh && bash scripts/gen-dash-tls.sh && bash scripts/rotate-bridge-token.sh

export: ## bundle the whole fleet's portable state (Layer 1) → one archive to move to another host. ARGS='--gpg you@host'
	@bash scripts/export-fleet.sh $(ARGS)

import: ## restore a fleet bundle onto this host (Layer 3 preflight → Layer 1 restore → Layer 2 make boot). ARGS='<bundle.tar.gz> [--dry-run] [--yes]'
	@bash scripts/import-fleet.sh $(ARGS)

audit-rebaseline: ## re-baseline the admin-audit chain after a benign key rotation (e.g. post-restore): archive old chain verbatim + fresh genesis. ARGS='--dry-run' to just diagnose
	@bash scripts/audit-rebaseline.sh $(ARGS)

siem-export: ## emit the fleet's security/governance events as OCSF NDJSON for a SIEM (Splunk/Elastic/Sentinel), tagged MITRE ATLAS/ATT&CK/D3FEND. Pipe to a forwarder.
	@bash scripts/siem-export.sh

metrics-export: ## render the fleet's state as Prometheus exposition text (node_exporter textfile collector / any scraper) for Grafana + Alertmanager
	@bash scripts/metrics-export.sh

lint: ## syntax-check every shell script + py-compile services
	@set -e; for f in $$(find lib scripts tests eval services provisioning -name '*.sh'); do bash -n "$$f"; done; echo "shell OK"
	@set -e; for p in $$(find services eval -name '*.py'); do python3 -m py_compile "$$p"; done; echo "python OK"

test: ## run unit tests (pure logic; no live stack needed)
	python3 -m unittest discover -s tests/unit -p 'test_*.py'

uitest: ## run UI render tests (jsdom; catches i18n leaks, blank views, dead wiring)
	@cd tests/ui && [ -d node_modules ] || npm install --silent jsdom >/dev/null 2>&1; cd $(CURDIR) && node --test tests/ui/ui.test.mjs

itest: ## run integration tests (services started standalone; python3 + curl only, no live stack)
	@set -e; for t in tests/integration/*.sh; do echo "→ $$t"; bash "$$t"; done

# --error: exit 1 on any finding, so this actually gates CI (make security-scan used to always
# exit 0 regardless of findings — see docs/design/architecture.md if that changes again).
# --timeout 120 --timeout-threshold 0: the defaults (30s / stop-after-3-timeouts-per-file) were
# silently skipping the rest of the ruleset on worker-itops.py (our largest file) once 3 rules
# timed out on it — a scan that reports "0 findings" because it gave up isn't a real all-clear.
# Rules excluded repo-wide (not per-finding nosemgrep, because every instance found across the
# whole repo was the same non-issue for this codebase specifically):
#   i18next-key-format — assumes a "MODULE.FEATURE.*" translation-key convention; this repo's own
#     i18n (t('English sentence')) deliberately uses full source strings as keys instead.
#   arbitrary-sleep — this codebase's agents are plain `while True: ...; time.sleep(interval)`
#     polling/scheduling loops throughout (no async framework, no cron lib) — sleep IS the
#     scheduling primitive here, not a debug leftover.
#   dynamic-urllib-use-detected — every instance is a fixed host (github/osv.dev/local NIM) with
#     only the path or an operator-configured device IP varying, not an attacker-redirectable SSRF.
#   subprocess-shell-true / dangerous-subprocess-use-audit — both blunt "shell=True is used at
#     all" / "argument isn't a literal" checks, with no taint analysis. This codebase's own sh()
#     helpers (worker-itops.py, agent-dashboard.py) are shell=True by design, contractually
#     requiring every caller to shlex.quote() + regex-validate untrusted segments — checked
#     individually across ~20 call sites, all compliant. nemofleet-py-command-injection (this
#     repo's own taint rule, NOT excluded) is what actually catches real injection here: it traces
#     source→sink and understands when a value was never sanitized, instead of flagging the
#     pattern this whole codebase deliberately and safely uses everywhere.
security-scan: ## scan THIS repo (not an upstream sync) with the same Semgrep ruleset worker-b uses; exits 1 on any finding
	@command -v semgrep >/dev/null 2>&1 || { \
	  echo "semgrep not on PATH — install it once: pip3 install --user semgrep"; exit 1; }
	@bash scripts/fetch-semgrep-rules.sh
	semgrep scan --config .cache/semgrep-rules \
	  --exclude-rule cache.semgrep-rules.typescript.react.portability.i18next.i18next-key-format \
	  --exclude-rule cache.semgrep-rules.python.lang.best-practice.arbitrary-sleep \
	  --exclude-rule cache.semgrep-rules.python.lang.security.audit.dynamic-urllib-use-detected \
	  --exclude-rule cache.semgrep-rules.python.lang.security.audit.subprocess-shell-true \
	  --exclude-rule cache.semgrep-rules.python.lang.security.audit.dangerous-subprocess-use-audit \
	  --metrics=off --error --timeout 120 --timeout-threshold 0 .

eval: ## run the fleet-competency eval harness (score + lessons sedimentation); needs a live boot
	@bash eval/eval.sh

clean: ## remove runtime junk (bus messages, logs, pycache) — keeps dirs
	find data/bus -type f ! -name '.gitkeep' -delete 2>/dev/null || true
	find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
	find data/logs -type f ! -name '.gitkeep' -delete 2>/dev/null || true
	@echo "cleaned"
