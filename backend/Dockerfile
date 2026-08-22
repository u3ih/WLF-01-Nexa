# Nexa backend — read-only statement analysis API.
# Keep Node on the version required by the Puppeteer lockfile. Debian's
# nodejs package currently lags behind and only emits an engine warning during
# npm ci, then can fail when the scheduled scraper actually runs.
FROM node:22-bookworm-slim AS node-runtime

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend

# Reuse the official Node runtime while keeping Python as the final base image.
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl chromium \
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
    CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/api/health" || exit 1

# Railway injects PORT. The fallback keeps Docker Compose and local runs on
# port 8000 without requiring another environment variable.
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
