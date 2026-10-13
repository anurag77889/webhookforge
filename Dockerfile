FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Shared directory for prometheus-client multiprocess mode (mounted as a
# named volume in docker-compose so the API and the Celery worker both write
# to it).
RUN mkdir -p /tmp/prometheus

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
