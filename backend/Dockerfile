# Nexa backend — read-only statement analysis API.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl nodejs npm chromium \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/data ./data
COPY migrations ../migrations
COPY backend/pytest.ini ./
COPY backend/tests ./tests
COPY dataset ../dataset

# The application scheduler invokes this scraper directly; no host crontab is
# needed. Install only the runtime JS dependencies and keep the output volume
# outside the image.
COPY scripts/yopmail_scraper/package*.json ../scripts/yopmail_scraper/
RUN cd ../scripts/yopmail_scraper \
    && PUPPETEER_SKIP_DOWNLOAD=true npm ci --omit=dev --no-audit --no-fund
COPY scripts/yopmail_scraper/scrape_full.js ../scripts/yopmail_scraper/
ENV NEXA_YOPMAIL_SCRAPER_DIR=/app/scripts/yopmail_scraper \
    NEXA_YOPMAIL_DATASET_DIR=/app/dataset \
    NEXA_YOPMAIL_NODE=node \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# The sample dataset is generated at build time so the image is self-contained.
RUN python -m data.generate

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
