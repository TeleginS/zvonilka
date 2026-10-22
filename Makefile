# make help — list the commands.
# Server targets use HOST from ~/.ssh/config: make server-logs HOST=other

HOST ?= aeza
REMOTE_DIR ?= /opt/zvonilka
SSH = ssh $(HOST) 'cd $(REMOTE_DIR) &&
VERSION ?=

.DEFAULT_GOAL := help
.PHONY: help install test routing-tests run env-check setup-agents sync-agents \
        up down restart logs ps deploy deploy-env \
        server-logs server-ps server-restart server-env-check server-sync-agents release

help: ## List the commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# Local development

install: ## Install dependencies (uv sync)
	uv sync

test: ## Unit tests, Retell and LLM mocked
	uv run pytest

routing-tests: ## How the real LLM parses requests; dials nobody
	uv run zvonilka-routing-tests

run: ## Run the bot locally without Docker
	uv run zvonilka

env-check: ## Which variables in .env are set (values aren't printed)
	uv run python -m zvonilka.env_check .env

# Retell voice agents

setup-agents: ## Create the Retell agents once, print ids for .env
	uv run zvonilka-setup-agents

sync-agents: ## Apply zvonilka/robot.py to the existing agents
	uv run zvonilka-sync-agents

# Local Docker

up: ## Build and start the local container
	docker compose up -d --build

down: ## Stop the local container (the database volume stays)
	docker compose down

restart: ## Restart the local container, re-reading .env
	docker compose up -d --force-recreate

logs: ## Follow the local bot's logs
	docker compose logs -f bot

ps: ## Local container status
	docker compose ps

# Server

deploy: ## Build for the server, ship over SSH, restart (keeps the server's .env)
	deploy/deploy.sh $(HOST)

deploy-env: ## Same, and upload .env.$(HOST) as the server's .env
	ENV_FILE=1 deploy/deploy.sh $(HOST)

server-logs: ## Follow the server bot's logs
	$(SSH) docker compose logs -f bot'

server-ps: ## Server container status
	$(SSH) docker compose ps'

server-restart: ## Restart the server container, re-reading its .env
	$(SSH) docker compose up -d --no-build --force-recreate'

server-env-check: ## Which variables the server container sees (values aren't printed)
	$(SSH) docker compose run --rm -T bot python -m zvonilka.env_check -'

server-sync-agents: ## Run sync-agents with the server's .env
	$(SSH) docker compose run --rm -T bot zvonilka-sync-agents'

# Release

release: ## Tag VERSION and push it; CI tests and publishes the image to GHCR
	@test -n "$(VERSION)" || (echo "usage: make release VERSION=v0.1.0" && exit 1)
	git tag $(VERSION)
	git push origin $(VERSION)
