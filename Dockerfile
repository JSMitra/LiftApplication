FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies if required
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY app/ ./app/

# Expose HTTP port
EXPOSE 8000

# Default entrypoint script that selects service based on SERVICE_TYPE environment variable
# SERVICE_TYPE: 'lift' or 'orchestrator'
CMD ["sh", "-c", "if [ \"$SERVICE_TYPE\" = \"lift\" ]; then exec uvicorn app.lift.main:app --host 0.0.0.0 --port ${LIFT_PORT:-8000}; else exec uvicorn app.orchestrator.main:app --host 0.0.0.0 --port ${ORCHESTRATOR_PORT:-8000}; fi"]

