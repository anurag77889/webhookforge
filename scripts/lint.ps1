# Lint + type-check.
docker compose run --rm api ruff check app/ tests/
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
docker compose run --rm api mypy app/
