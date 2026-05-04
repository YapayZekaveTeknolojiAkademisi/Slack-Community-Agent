# Slack Community Agent — Docker / Compose yardimcilari
# Kullanim: make help

.PHONY: help up up-build down down-v ps logs build rebuild pull \
	migrate migrate-fresh logs-challenge logs-event logs-postgres \
	up-feature up-english up-summary shell-challenge config check

COMPOSE ?= docker compose
# Belirli servisin logu: make logs S=event
S ?= challenge

help: ## Bu yardim listesi
	@echo "Slack Community Agent — make komutlari"
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' Makefile | sort | sed 's/\(.\+\):.*## /  \1\t/'
	@echo ""
	@echo "Ornekler:"
	@echo "  make up              # postgres + migrate + challenge + event"
	@echo "  make logs S=event    # event konteyner logu"
	@echo "  make up-english      # + english (profil; challenge ile Socket birlestirme)"

check: ## docker ve compose erisilebilir mi
	@docker info >/dev/null && docker compose version

config: ## compose yapilandirmasini dogrula ( stdout )
	$(COMPOSE) config

up: ## Varsayilan stack (arka planda)
	$(COMPOSE) up -d

up-build: ## Guncel imajlarla kaldirip stack
	$(COMPOSE) up -d --build

down: ## Stack durdurur (volume kalir)
	$(COMPOSE) down

down-v: ## Stack + pgdata/hf_cache volume silinir (DİKKAT: DB verisi gider)
	$(COMPOSE) down -v

ps: ## Konteyner durumu
	$(COMPOSE) ps -a

build: ## Imajlari derle (konteyner calistirmadan)
	$(COMPOSE) build

rebuild: ## Onceden cache kullanmadan derle
	$(COMPOSE) build --no-cache

pull: ## Taban imajlari cek (postgres vb.)
	$(COMPOSE) pull postgres 2>/dev/null || true

logs: ## Log: S=challenge|event|postgres|migrate (varsayilan: challenge)
	$(COMPOSE) logs -f $(S)

logs-challenge: ## challenge log
	$(COMPOSE) logs -f challenge

logs-event: ## event log
	$(COMPOSE) logs -f event

logs-postgres: ## postgres log
	$(COMPOSE) logs -f postgres

migrate: ## Sadece alembic upgrade (postgres ayakta olmali)
	$(COMPOSE) run --rm migrate

migrate-fresh: ## postgres + migrate (temiz DB ile deneme icin once make down-v)
	@echo "Once: make down-v && make up  — veya mevcut DB uzerinde: make migrate"

shell-challenge: ## challenge konteynerinde bash
	$(COMPOSE) exec challenge bash

up-feature: ## feature-request + taban stack (ayri Socket; challenge ile birlikte calistirma)
	$(COMPOSE) --profile feature-standalone up -d

up-english: ## english + taban stack (ayri Socket)
	$(COMPOSE) --profile english-standalone up -d

up-summary: ## summary + taban stack (ayri Socket)
	$(COMPOSE) --profile summary-standalone up -d
