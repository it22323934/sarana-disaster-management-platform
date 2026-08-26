# syntax=docker/dockerfile:1
# Build with: docker build -f services/alerting-svc/Dockerfile -t sarana/alerting-svc .
# (context = repo root, so this can pull in packages/py-shared as a workspace member)

FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir uv==0.12.6

WORKDIR /build
COPY pyproject.toml uv.lock* ./
COPY packages/py-shared packages/py-shared
COPY services/alerting-svc services/alerting-svc

RUN --mount=type=cache,target=/root/.cache/uv \
    uv build --package sarana-shared --wheel -o /build/dist packages/py-shared && \
    uv build --package alerting-svc --wheel -o /build/dist services/alerting-svc

FROM python:3.12-slim AS dev
# Used by infra/docker/compose.yml (target: dev) for local hot-reload. Editable-installs
# both packages against the mounted source, so a change on the host is live immediately —
# the `runtime` stage below (wheel-installed, non-root) is what actually ships.

RUN pip install --no-cache-dir uv==0.12.6

WORKDIR /app
COPY pyproject.toml uv.lock* ./
COPY packages/py-shared packages/py-shared
COPY services/alerting-svc services/alerting-svc

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -e packages/py-shared -e "services/alerting-svc[test]"

EXPOSE 8003
CMD ["uvicorn", "alerting_svc.main:app", "--host", "0.0.0.0", "--port", "8003", \
     "--reload", "--reload-dir", "/app/services/alerting-svc/src"]

FROM python:3.12-slim AS runtime

RUN groupadd --system sarana && useradd --system --gid sarana --no-create-home sarana

WORKDIR /app
COPY --from=builder /build/dist/*.whl /tmp/wheels/
RUN pip install --no-cache-dir /tmp/wheels/*.whl && rm -rf /tmp/wheels

USER sarana
EXPOSE 8003

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8003/healthz')" || exit 1

CMD ["uvicorn", "alerting_svc.main:app", "--host", "0.0.0.0", "--port", "8003"]
