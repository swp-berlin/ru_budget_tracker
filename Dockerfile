# ==============================================================================
# Stage 1: Build stage
# Downloads and installs all dependencies needed for building
# ==============================================================================
FROM python:3.13@sha256:2deb0891ec3f643b1d342f04cc22154e6b6a76b41044791b537093fae00b6884 AS builder

# Copy UV from Astral's image to have a consistent and minimal base
COPY --from=ghcr.io/astral-sh/uv:0.9.10 /uv /uvx /bin/

# Copy project dependencies files
WORKDIR /app
COPY pyproject.toml uv.lock ./

# Set environment path to global site-packages
ENV UV_PROJECT_ENVIRONMENT=/usr/local

# Install dependencies
RUN uv sync --locked --no-dev


# ==============================================================================
# Stage 2: Deploy stage
# Uses slim image to reduce final image size
# ==============================================================================
FROM python:3.13-slim@sha256:58c30f5bfaa718b5803a53393190b9c68bd517c44c6c94c1b6c8c172bcfad040 AS deploy

WORKDIR /app

# Copy dependencies and application files
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY ./src /app
COPY ./pyproject.toml /app


# Install curl for healthcheck and clean up in single layer
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*


# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser && \
    chown -R appuser:appuser /app
USER appuser

# Add health check for the MCP server
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

ENV PYTHONPATH=.

CMD [ "sh", "-c", "alembic upgrade head && python -m scripts.mock_data.populate_database && gunicorn app:app --bind 0.0.0.0:8000"]