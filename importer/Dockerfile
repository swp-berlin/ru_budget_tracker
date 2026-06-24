FROM docker.io/library/python:3.14-slim-trixie
# Official way to get uv and uvx into the image, see https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Create non-root user to increase security
RUN groupadd -g 1001 svc && \
    useradd -d /home/appuser -m -u 1001 -g svc appuser

WORKDIR /home/appuser/app

COPY --chown=appuser:svc pyproject.toml README.md .env ./
COPY --chown=appuser:svc src ./src

# Install dependencies (clean cache, upgrade packages)
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    uv sync
    #chown -R appuser:svc /app

# Switch to non-root user
USER appuser

CMD ["uv", "run", "python", "-m", "importer"]