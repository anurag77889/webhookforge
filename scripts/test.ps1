# Run the test suite with coverage.
# Usage: .\scripts\test.ps1 [-Filter <pytest args>]
docker compose run --rm api pytest tests/ -v --cov=app --cov-report=term-missing @args
