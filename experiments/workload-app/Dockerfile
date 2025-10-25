# Use official Python slim image
FROM python:3.13-alpine

RUN apk update && apk add --no-cache build-base gfortran blas-dev lapack-dev

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

# Copy logging configuration for uvicorn
COPY logging.yaml /app/

# Expose port
EXPOSE 8080

# Run the FastAPI app
CMD ["poetry", "run", "uvicorn", "app:app", "--host", "0.0.0.0", "--log-config", "logging.yaml", "--port", "8080"]

