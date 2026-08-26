# syntax=docker/dockerfile:1
# Build with: docker build -f services/gov-mock/Dockerfile -t sarana/gov-mock .
# (context = repo root, so this can pull in packages/py-shared as a workspace member)

FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir uv==0.12.6

WORKDIR /build
COPY pyproject.toml uv.lock* ./
COPY packages/py-shared packages/py-shared
COPY services/gov-mock services/gov-mock

RUN --mount=type=cache,target=/root/.cache/uv \
    uv build --package sarana-shared --wheel -o /build/dist packages/py-shared && \
    uv build --package gov-mock --wheel -o /build/dist services/gov-mock

FROM python:3.12-slim AS dev
# Used by infra/docker/compose.yml (target: dev) for local hot-reload. Editable-installs
# both packages against the mounted source, so a change on the host is live immediately —
# the `runtime` stage below (wheel-installed, non-root) is what actually ships.

RUN pip install --no-cache-dir uv==0.12.6

WORKDIR /app
COPY pyproject.toml uv.lock* ./
COPY packages/py-shared packages/py-shared
COPY services/gov-mock services/gov-mock

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -e packages/py-shared -e "services/gov-mock[test]"

EXPOSE 8006
CMD ["uvicorn", "gov_mock.main:app", "--host", "0.0.0.0", "--port", "8006", \
     "--reload", "--reload-dir", "/app/services/gov-mock/src"]

FROM python:3.12-slim AS runtime

RUN groupadd --system sarana && useradd --system --gid sarana --no-create-home sarana

WORKDIR /app
COPY --from=builder /build/dist/*.whl /tmp/wheels/
RUN pip install --no-cache-dir /tmp/wheels/*.whl && rm -rf /tmp/wheels

USER sarana
EXPOSE 8006

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8006/healthz')" || exit 1

CMD ["uvicorn", "gov_mock.main:app", "--host", "0.0.0.0", "--port", "8006"]
