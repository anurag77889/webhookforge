.PHONY: dev down test seed lint migrate shell logs

dev:
	docker compose up --build

down:
	docker compose down

test:
	docker compose run --rm api pytest tests/ -v --cov=app --cov-report=term-missing

seed:
	docker compose run --rm api python scripts/seed.py

lint:
	docker compose run --rm api ruff check app/ tests/
	docker compose run --rm api mypy app/

migrate:
	docker compose run --rm api alembic upgrade head

shell:
	docker compose exec api bash

logs:
	docker compose logs -f api celery_worker
