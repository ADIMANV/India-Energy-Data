# Single image for both the API server and the scraper tick.
# Build context is the repo root:  docker build -f deploy/Dockerfile .
FROM python:3.12-slim

WORKDIR /app

COPY scrapers/ scrapers/
COPY api/ api/
COPY scripts/ scripts/
RUN pip install --no-cache-dir ./scrapers ./api

# default: API server. The tick service overrides with `python -m gridscrapers.tick`.
CMD ["uvicorn", "gridapi.main:app", "--host", "0.0.0.0", "--port", "8000"]
