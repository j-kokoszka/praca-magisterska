# Use official Python slim image
FROM python:3.11-slim

# Install Poetry
RUN pip install --no-cache-dir poetry

# Set working directory
WORKDIR /app

# Copy dependency definitions
COPY pyproject.toml poetry.lock* /app/

# Install dependencies only, do not install the project as a package
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root

# Copy application code
COPY app.py /app/

# Expose port
EXPOSE 8080

# Run the FastAPI app
CMD ["poetry", "run", "uvicorn", "app:app", "--host", "0.0.0.0", "--log-level", "debug", "--access-log", "--port", "8080"]

