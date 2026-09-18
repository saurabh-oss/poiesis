FROM python:3.12-slim

# docker-cli, not docker.io: the orchestrator only needs the *client*, to launch
# sandbox containers on the host daemon through the mounted socket. On Debian 13
# the docker.io package installs the runtime without putting a `docker` binary on
# PATH, which fails at the first test run rather than at build time.
# docker-compose provides the `docker compose` plugin that starts generated apps.
RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl build-essential ca-certificates ffmpeg docker-cli docker-compose \
    && rm -rf /var/lib/apt/lists/* \
    && docker --version \
    && docker compose version

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY packs ./packs
COPY scaffolds ./scaffolds

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
