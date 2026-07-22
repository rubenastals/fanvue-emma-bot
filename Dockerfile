FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ACCOUNT_ID=emma

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cursor SDK for hourly cloud review / autofix runners
COPY tools/fixer/package.json tools/fixer/package-lock.json tools/fixer/
RUN cd tools/fixer && npm ci --omit=dev

COPY . .

# Production entrypoint: Fanvue inbox poller (not the legacy webhook API).
CMD ["python", "scripts/poll_inbox.py", "--interval", "10"]
