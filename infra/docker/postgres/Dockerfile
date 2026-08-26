# PostgreSQL 16 with PostGIS 3.4 and pgvector - the one datastore (ADR-002).
#
# postgis/postgis is built on the official postgres image and already has the PGDG apt
# repository configured, so pgvector comes from the same packaging channel as PostGIS
# itself. Building pgvector from source here would also mean shipping a compiler in a
# database image, and the base image's pgxs config expects an LLVM toolchain it does not
# actually carry.

FROM postgis/postgis:16-3.4

RUN apt-get update \
    && apt-get install --no-install-recommends -y postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*

COPY init/ /docker-entrypoint-initdb.d/
