FROM python:3.11.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .

# One worker: scrape jobs are kept in memory, so all requests must hit the same process.
CMD gunicorn app:app --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:${PORT:-5000}
