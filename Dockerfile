FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent code
COPY src/ /app/src/

# Set env vars
ENV PYTHONPATH=/app/src

# Entry point for the agent
ENTRYPOINT ["python", "src/agent.py"]
