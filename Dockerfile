FROM python:3.11-slim

# OpenCV needs these system libs even in "headless" mode
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend
COPY frontend frontend
COPY models models

ENV PPE_MODEL_PATH=/app/models/finalboss.pt
ENV PPE_DB_PATH=/app/data/ppe_platform.db
# Mount a volume on /app/data if you want the database (users, settings,
# event history) to survive container rebuilds:
#   docker run -v ppe_data:/app/data ...
EXPOSE 8000

WORKDIR /app/backend
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
