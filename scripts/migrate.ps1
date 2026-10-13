# Apply database migrations.
docker compose run --rm api alembic upgrade head
