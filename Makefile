.PHONY: help build start stop restart logs status test clean

# Default target listing all commands
help:
	@echo "Envira Loss-Experience Service - Management Commands"
	@echo "======================================================"
	@echo "  make start     : Build and start service in background (port 8000)"
	@echo "  make stop      : Stop and remove service container"
	@echo "  make restart   : Stop and restart service"
	@echo "  make test      : Run full test suite (reconciliation included) in Docker"
	@echo "  make logs      : Follow real-time container logs"
	@echo "  make status    : Display service health and container status"
	@echo "  make clean     : Remove containers, networks, and orphaned volumes"

build:
	docker compose build

start:
	docker compose up --build -d

stop:
	docker compose down

restart: stop start

logs:
	docker compose logs -f

status:
	docker compose ps

test:
	docker compose run --rm loss-experience-api pytest -v

clean:
	docker compose down -v --remove-orphans
