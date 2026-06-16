# 1. Start with an official Python image
FROM python:3.11-slim

# 2. Set the working directory inside the container
WORKDIR /app

# 3. Install basic system dependencies needed for Python packages
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 4. Copy just your requirements file first (this makes building faster later)
COPY requirements.txt .

# 5. Install your Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copy the rest of your project files into the container
COPY . .

# 7. Tell Docker what command to run by default when it turns on
CMD ["python", "services/processor/src/worker.py"]