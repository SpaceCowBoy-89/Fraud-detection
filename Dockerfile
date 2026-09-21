FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=5050 \
    WEB_CONCURRENCY=1 \
    GUNICORN_TIMEOUT=120

EXPOSE 5050

# Production WSGI server (Flask dev server: use `docker compose run --rm web python run.py ...`)
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY} --timeout ${GUNICORN_TIMEOUT} --access-logfile - --error-logfile - wsgi:application"]
