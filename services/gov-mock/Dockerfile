# SARANA Government and Telco Mocks
# Multi-stage, non-root, no build toolchain in the runtime layer.
# Builds on linux/amd64 and linux/arm64: the team is on Macs, Fargate is amd64.

FROM --platform=$BUILDPLATFORM ghcr.io/astral-sh/uv:0.5-python3.12-bookworm-slim AS builder

# UV_HTTP_TIMEOUT: six service images build against one uplink, and the 30s default
# times out on the larger wheels (cryptography, shapely) when builds overlap.
#
# UV_PROJECT_ENVIRONMENT: build the virtualenv at the path it will finally live at.
# Console scripts bake an absolute shebang, so a venv built elsewhere and copied into
# place fails at container start with "exec .../uvicorn: no such file or directory".
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_HTTP_TIMEOUT=180 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /build

# Copy only what the resolver needs first, so a source edit does not invalidate the
# dependency layer.
COPY pyproject.toml uv.lock ./
COPY packages/py-shared/pyproject.toml packages/py-shared/
COPY services/gov-mock/pyproject.toml services/gov-mock/

RUN --mount=type=cache,target=/root/.cache/uv     uv sync --frozen --no-install-workspace --package sarana-gov-mock

COPY packages/py-shared/ packages/py-shared/
COPY services/gov-mock/ services/gov-mock/

RUN --mount=type=cache,target=/root/.cache/uv     uv sync --frozen --no-editable --package sarana-gov-mock


FROM python:3.12-slim-bookworm AS runtime

# curl is the container healthcheck; nothing else is added to the runtime image.
RUN apt-get update     && apt-get install --no-install-recommends -y curl     && rm -rf /var/lib/apt/lists/*     && groupadd --system --gid 1001 sarana     && useradd --system --uid 1001 --gid sarana --create-home sarana

ENV PATH="/app/.venv/bin:$PATH"     PYTHONUNBUFFERED=1     PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=builder --chown=sarana:sarana /app/.venv /app/.venv
COPY --from=builder --chown=sarana:sarana /build/services/gov-mock /app/services/gov-mock

USER sarana

EXPOSE 8006

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5     CMD curl -fsS http://localhost:8006/healthz || exit 1

CMD ["uvicorn", "--factory", "gov_mock.main:build_app", "--host", "0.0.0.0", "--port", "8006"]
