ARG PYTHON_BASE_IMAGE=python:3.12.13-alpine3.23@sha256:601d3d3797e90e2534782e69c85fafb7971b43f24c7b1b079b7e48dd435e458d

# checkov:skip=CKV_DOCKER_7:The release workflow supplies no override and verifies this exact version-and-digest default before building. [owner=modelguard-maintainers; expires=2026-10-31]
FROM ${PYTHON_BASE_IMAGE} AS dependencies
ARG UV_VERSION=0.12.1
ENV UV_COMPILE_BYTECODE=1 \
    UV_HTTP_TIMEOUT=120 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /build
RUN apk add --no-cache build-base gfortran linux-headers
RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}"
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --only-group docker-monitor --no-install-project

FROM ${PYTHON_BASE_IMAGE} AS runtime
ARG SOURCE_REVISION=local-uncommitted
ARG UV_LOCK_SHA256=9280d58d41655d0d06899ec465b8147844912a800d213e16321522337cd947be
LABEL org.opencontainers.image.title="ModelGuard AI Monitor" \
      org.opencontainers.image.description="One-shot deterministic local drift monitor" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      io.modelguard.uv-lock.sha256="${UV_LOCK_SHA256}" \
      io.modelguard.component="monitor"
ENV HOME=/home/modelguard \
    PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1
WORKDIR /app
RUN apk add --no-cache libgomp libstdc++ \
    && addgroup -S -g 10001 modelguard \
    && adduser -S -D -u 10001 -G modelguard -h /home/modelguard \
        -s /sbin/nologin modelguard \
    && install -d -o modelguard -g modelguard -m 0750 /model /runtime \
    && find / -xdev -type f \( -perm -4000 -o -perm -2000 \) -exec chmod ug-s {} +
COPY --from=dependencies --chown=10001:10001 /build/.venv /app/.venv
COPY --chown=10001:10001 src /app/src
COPY --chown=10001:10001 configs/phase-05-monitoring.json /app/configs/phase-05-monitoring.json
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=2 \
    CMD ["python", "-c", "import os; import modelguard.monitoring.cli; raise SystemExit(0 if os.geteuid() != 0 else 1)"]
ENTRYPOINT ["python", "-m", "modelguard.monitoring.cli"]
CMD ["--help"]
