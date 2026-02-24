FROM python:3.11-slim

WORKDIR /app

# System dependencies
# libpq-dev   — PostgreSQL client headers (for asyncpg)
# build-essential — needed to compile some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download LiveKit model files (silero VAD + turn-detector)
# These are needed by the agent worker at startup.
COPY agent/ ./agent/
COPY run_agent.py .
RUN python run_agent.py download-files

# Copy remaining application source
COPY app/ ./app/

# Non-root user for security
RUN adduser --disabled-password --gecos "" appuser
USER appuser

EXPOSE 8000

# Default command runs the FastAPI app.
# The agent worker is run as a separate container (see docker-compose.yml).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
