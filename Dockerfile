# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

FROM ${PYTHON_IMAGE} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip wheel --wheel-dir /wheels ".[interfaces,llm,workflow]"

FROM ${PYTHON_IMAGE} AS runtime

ARG APP_UID=10001
ARG APP_GID=10001
ARG VERSION=0.1.0
ARG REVISION=local

LABEL org.opencontainers.image.title="ResolveOps" \
      org.opencontainers.image.description="Enterprise service and operations resolution platform" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/home/resolveops/.local/bin:${PATH}"

RUN groupadd --gid "${APP_GID}" resolveops \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home resolveops

COPY --from=builder /wheels /wheels
RUN python -m pip install --no-index --find-links=/wheels "resolveops[interfaces,llm,workflow]" \
    && rm -rf /wheels

WORKDIR /app
COPY --chown=resolveops:resolveops alembic.ini ./
COPY --chown=resolveops:resolveops migrations ./migrations
COPY --chown=resolveops:resolveops domain_packs ./domain_packs

USER resolveops
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3).read()"]

CMD ["uvicorn", "resolveops.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
