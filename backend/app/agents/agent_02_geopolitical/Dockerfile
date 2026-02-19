FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy model
RUN python -m spacy download en_core_web_sm

# Copy source
COPY . .

# Create non-root user
RUN useradd -m -u 1000 geokg && chown -R geokg:geokg /app
USER geokg

EXPOSE 8000

CMD ["python", "main.py", "server", "--host", "0.0.0.0"]
