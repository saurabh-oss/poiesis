# Postgres with this application's schema baked in.
#
# Not bind-mounted: Poiesis deploys through the Docker socket, and the host
# daemon cannot see the workspace path the orchestrator reads it from.
FROM postgres:16-alpine
COPY init.sql /docker-entrypoint-initdb.d/init.sql
