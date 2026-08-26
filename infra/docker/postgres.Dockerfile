# PostGIS + pgvector in one image. Base already has PostGIS; this just adds the
# pgvector extension binaries and creates it at init time via the docker-entrypoint
# initdb.d convention.
FROM postgis/postgis:16-3.4

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*

COPY infra/docker/postgres-init.sql /docker-entrypoint-initdb.d/10-extensions.sql
