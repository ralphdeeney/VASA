# Build from the repository root after scripts/prepare_evolution.py prepares the CA bundle.
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS build

RUN groupadd --gid 1000 vasa && useradd --uid 1000 --gid 1000 --create-home vasa \
    && mkdir -p /opt/uv /opt/vasa && chown vasa:vasa /opt/uv /opt/vasa
COPY --chmod=0644 .local/evolution-source/vasa-host-trust.pem /usr/local/share/vasa-host-trust.pem
ENV UV_NATIVE_TLS=true \
    SSL_CERT_FILE=/usr/local/share/vasa-host-trust.pem \
    PIP_CERT=/usr/local/share/vasa-host-trust.pem \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_PROJECT_ENVIRONMENT=/opt/vasa/.venv \
    PATH=/opt/uv/bin:/opt/vasa/.venv/bin:$PATH
USER 1000:1000
WORKDIR /opt/vasa
RUN python -m pip install --no-cache-dir --target /opt/uv uv==0.12.19
COPY --chown=1000:1000 pyproject.toml uv.lock ./
COPY --chown=1000:1000 src/ ./src/
RUN uv sync --frozen --no-dev --no-editable --no-cache

FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 1000 vasa && useradd --uid 1000 --gid 1000 --create-home vasa
COPY --from=build /usr/local/share/vasa-host-trust.pem /usr/local/share/vasa-host-trust.pem
COPY --from=build --chown=0:0 /opt/vasa/.venv /opt/vasa/.venv
COPY --chmod=0755 --chown=0:0 migrations/ /opt/vasa/migrations/
COPY --chmod=0644 --chown=0:0 alembic.ini /opt/vasa/alembic.ini
COPY --chmod=0644 --chown=0:0 scripts/evolution_status.py /opt/vasa/scripts/evolution_status.py
COPY --chmod=0644 --chown=0:0 scripts/prepare_speech.py /opt/vasa/scripts/prepare_speech.py
RUN find /opt/vasa/migrations -type f -exec chmod 0644 {} + \
    && chmod 0755 /opt/vasa/scripts \
    && mkdir /opt/vasa/.local && chown 1000:1000 /opt/vasa/.local \
    && chmod 0700 /opt/vasa/.local
ENV PATH=/opt/vasa/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_NATIVE_TLS=true \
    SSL_CERT_FILE=/usr/local/share/vasa-host-trust.pem \
    PIP_CERT=/usr/local/share/vasa-host-trust.pem
USER 1000:1000
WORKDIR /opt/vasa
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/live', timeout=2).close()"]
CMD ["uvicorn", "vasa.app:app", "--host", "0.0.0.0", "--port", "8080", "--limit-concurrency", "100", "--timeout-keep-alive", "5", "--no-server-header"]
