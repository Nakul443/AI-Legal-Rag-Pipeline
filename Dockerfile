FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for compiling specific vector libraries or binaries
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy python dependencies layout
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- ADDED: Playwright Browser Installation Layer ---
# Installs the matching Chromium binaries and necessary Linux system libraries 
# inside the isolated container filesystem to prevent launch executable crashes.
RUN playwright install --with-deps chromium

# --- ADDED: Crawl4AI Internal Setup Broker ---
# Triggers internal browser configurations so crawl4ai accurately recognizes 
# its custom headless engine environment mappings.
RUN crawl4ai-setup

# Copy the entire workspace structure into the container (/app/services, /app/models, etc.)
COPY . .

# Set PYTHONPATH so Python can easily find cross-service module imports (like models.schema)
ENV PYTHONPATH=/app:/app/services/processor/src:/app/services/api-rag/src

# Default execution targeted directly at your pipeline entry point
CMD ["python3", "services/processor/src/worker.py"]