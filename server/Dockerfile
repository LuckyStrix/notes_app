FROM python:3.11-slim

WORKDIR /app

# pg_dump (used by the Settings "Export database" download) must match the
# database's major version, or the dump will not restore cleanly -- see the
# note in Dockerfile.worker. Keep the 16 in step with the pg16 image in compose.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && install -d /usr/share/keyrings \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/keyrings/pgdg.asc \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/keyrings/pgdg.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    libpq5 postgresql-client-16 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
