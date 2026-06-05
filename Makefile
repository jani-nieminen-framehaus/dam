# DAM build & run — cross-platform (Linux / macOS).
# Python is resolved in priority order: uv (project venv) > .venv > system python3.

UV := $(shell command -v uv 2>/dev/null)
ifdef UV
  PY := uv run python
else ifneq (,$(wildcard .venv/bin/python))
  PY := .venv/bin/python
else
  PY := python3
endif

FRONTEND := frontend
STATIC := static
UNAME := $(shell uname -s)

PREFIX ?= $(HOME)/.local
BINDIR := $(PREFIX)/bin
DESKTOPDIR := $(PREFIX)/share/applications
SYSTEMD_USER := $(HOME)/.config/systemd/user

.PHONY: build frontend backend run serve test clean help install uninstall watcher-install watcher-uninstall

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

build: frontend backend ## Full build: frontend + PyInstaller bundle

frontend: ## Build frontend (Vite → static/)
	cd $(FRONTEND) && NODE_ENV=development npm install --silent && NODE_ENV=development npm run build

backend: ## Build PyInstaller bundle (dist/dam or dist/DAM.app)
	$(PY) -m PyInstaller dam.spec --noconfirm

run: ## Run desktop app from source (development)
	$(PY) dam.py serve --window

serve: ## Run web server only (development)
	$(PY) dam.py serve

test: ## Run all tests
	$(PY) -m pytest tests/ -v

clean: ## Remove build artifacts
	rm -rf build/ dist/ *.egg-info

# ── Linux integration ────────────────────────────────────────────────────────

install: ## Linux: install `dam` launcher + desktop entry into ~/.local
	@mkdir -p $(BINDIR) $(DESKTOPDIR)
	@printf '#!/usr/bin/env bash\ncd %s && exec %s dam.py "$$@"\n' "$(CURDIR)" "$(PY)" > $(BINDIR)/dam
	@chmod +x $(BINDIR)/dam
	@sed -e 's|@EXEC@|$(BINDIR)/dam serve --window|' \
	     -e 's|@ICON@|$(CURDIR)/assets/icon.svg|' \
	     packaging/dam.desktop.in > $(DESKTOPDIR)/dam.desktop
	@echo "Installed $(BINDIR)/dam and $(DESKTOPDIR)/dam.desktop"
	@echo "Ensure $(BINDIR) is on your PATH."

uninstall: ## Linux: remove launcher + desktop entry
	@rm -f $(BINDIR)/dam $(DESKTOPDIR)/dam.desktop
	@echo "Removed dam launcher and desktop entry."

watcher-install: ## Linux: enable card-watcher systemd user service
	@mkdir -p $(SYSTEMD_USER)
	@sed -e 's|@WORKDIR@|$(CURDIR)|' -e 's|@PY@|$(PY)|' \
	     packaging/dam-card-watcher.service.in > $(SYSTEMD_USER)/dam-card-watcher.service
	@systemctl --user daemon-reload
	@systemctl --user enable --now dam-card-watcher.service
	@echo "Card watcher enabled. Logs: journalctl --user -u dam-card-watcher -f"

watcher-uninstall: ## Linux: disable card-watcher systemd user service
	@systemctl --user disable --now dam-card-watcher.service 2>/dev/null || true
	@rm -f $(SYSTEMD_USER)/dam-card-watcher.service
	@systemctl --user daemon-reload
	@echo "Card watcher disabled."
