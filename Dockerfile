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

# Copy the entire workspace structure into the container (/app/services, /app/models, etc.)
COPY . .

# Set PYTHONPATH so Python can easily find cross-service module imports (like models.schema)
ENV PYTHONPATH=/app:/app/services/processor/src:/app/services/api-rag/src

# Default execution targeted directly at your pipeline entry point
CMD ["python", "services/processor/src/worker.py"]