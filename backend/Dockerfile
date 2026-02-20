FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies for WeasyPrint (PDF) + build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies before copying source (layer cache optimisation)
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Create a writable directory for the SOC local blocklist log.
# In container mode BLOCK_LAYER_NGINX and BLOCK_LAYER_AZURE are both false
# by default, so only the local file is written (simulation/audit mode).
RUN mkdir -p /app/app/security && \
    touch /app/app/security/blocklist.conf

# Run as a non-root user for container security best practice
RUN addgroup --system sentinelai && \
    adduser --system --ingroup sentinelai sentinelai && \
    chown -R sentinelai:sentinelai /app

USER sentinelai

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
