# SARANA Agent Service
# Multi-stage, non-root, no build toolchain in the runtime layer.
# Builds on linux/amd64 and linux/arm64: the team is on Macs, Fargate is amd64.

FROM --platform=$BUILDPLATFORM ghcr.io/astral-sh/uv:0.5-python3.12-bookworm-slim AS builder

# Six service images build against one uplink, and the 30s default times out on the
# larger wheels (cryptography, shapely) when several builds run at once.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_HTTP_TIMEOUT=180

WORKDIR /build

# Copy only what the resolver needs first, so a source edit does not invalidate the
# dependency layer.
COPY pyproject.toml uv.lock ./
COPY packages/py-shared/pyproject.toml packages/py-shared/
COPY services/agent-svc/pyproject.toml services/agent-svc/

RUN --mount=type=cache,target=/root/.cache/uv     uv sync --frozen --no-install-workspace --package sarana-agent-svc

COPY packages/py-shared/ packages/py-shared/
COPY services/agent-svc/ services/agent-svc/

RUN --mount=type=cache,target=/root/.cache/uv     uv sync --frozen --no-editable --package sarana-agent-svc


FROM python:3.12-slim-bookworm AS runtime

# curl is the container healthcheck; nothing else is added to the runtime image.
RUN apt-get update     && apt-get install --no-install-recommends -y curl     && rm -rf /var/lib/apt/lists/*     && groupadd --system --gid 1001 sarana     && useradd --system --uid 1001 --gid sarana --create-home sarana

ENV PATH="/app/.venv/bin:$PATH"     PYTHONUNBUFFERED=1     PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=builder --chown=sarana:sarana /build/.venv /app/.venv
COPY --from=builder --chown=sarana:sarana /build/services/agent-svc /app/services/agent-svc

USER sarana

EXPOSE 8005

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5     CMD curl -fsS http://localhost:8005/healthz || exit 1

CMD ["uvicorn", "--factory", "agent_svc.main:build_app", "--host", "0.0.0.0", "--port", "8005"]
