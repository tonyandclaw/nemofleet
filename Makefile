# nemofleet — convenience targets. Scripts self-locate the repo root, so `make`
# works from anywhere in the tree.
SHELL := /bin/bash

.PHONY: help bootstrap boot health mail-up gen-certs lint test clean

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

lint: ## syntax-check every shell script + py-compile services
	@set -e; for f in $$(find lib scripts tests eval services provisioning -name '*.sh'); do bash -n "$$f"; done; echo "shell OK"
	@set -e; for p in $$(find services eval -name '*.py'); do python3 -m py_compile "$$p"; done; echo "python OK"

test: ## run unit tests (pure logic; no live stack needed)
	python3 -m unittest discover -s tests/unit -p 'test_*.py'

clean: ## remove runtime junk (bus messages, logs, pycache) — keeps dirs
	find data/bus -type f ! -name '.gitkeep' -delete 2>/dev/null || true
	find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
	find data/logs -type f ! -name '.gitkeep' -delete 2>/dev/null || true
	@echo "cleaned"
