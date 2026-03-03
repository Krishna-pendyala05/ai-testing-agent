FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent source code (includes src/tools/)
COPY src/ /app/src/

# Copy the target demo application (served by CI http.server on the host,
# but also available inside the container for direct file:// access if needed)
COPY app/ /app/app/

# Make the tools directory a proper Python package
RUN touch /app/src/tools/__init__.py

# Ensure src is in the Python path
ENV PYTHONPATH=/app/src

# The workspace directory is mounted from the host via -v in CI.
# We create it here as a fallback for local runs.
RUN mkdir -p /workspace

# Entry point: python src/agent.py <PR_NUMBER> "<PR_BODY>" "<TARGET_URL>"
ENTRYPOINT ["python", "/app/src/agent.py"]
