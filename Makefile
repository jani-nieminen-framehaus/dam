PYTHON := /opt/homebrew/bin/python3
FRONTEND := frontend
STATIC := static

.PHONY: build frontend backend run serve test clean icon help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

build: frontend backend ## Full build: frontend + PyInstaller app

frontend: ## Build frontend (Vite → static/)
	cd $(FRONTEND) && NODE_ENV=development npm install --silent && NODE_ENV=development npm run build

backend: ## Build PyInstaller app (dist/DAM.app)
	$(PYTHON) -m PyInstaller dam.spec --noconfirm

run: ## Run desktop app from source (development)
	$(PYTHON) dam.py serve --window

serve: ## Run web server only (development)
	$(PYTHON) dam.py serve

test: ## Run all tests
	$(PYTHON) -m pytest tests/ -v

clean: ## Remove build artifacts
	rm -rf build/ dist/ *.egg-info
