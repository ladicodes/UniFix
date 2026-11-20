# syntax=docker/dockerfile:1
# UniFix backend image. Build context: backend/
#   docker build -t unifix-backend backend
# Run migrations as a release step, not on every boot:
#   docker run --env-file backend/.env unifix-backend alembic upgrade head

FROM python:3.12-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir uv==0.13.7
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH" ENV=production
RUN groupadd --system unifix && useradd --system --gid unifix --home-dir /app --no-create-home unifix
WORKDIR /app
COPY --from=build --chown=unifix:unifix /app /app
USER unifix
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"
# The image runs as a non-root user and needs no writable paths except an optional /tmp; run it with a
# read-only root filesystem (e.g. `docker run --read-only --tmpfs /tmp`). Uploads go to S3 in production.
# --proxy-headers + --forwarded-allow-ips: trust X-Forwarded-For only from the platform's proxy.
# Set FORWARDED_ALLOW_IPS to the proxy address(es) in production.
# ENV defaults to production, so the settings validator refuses insecure configuration at boot.
CMD ["sh", "-c", "uvicorn --factory app.main:app_factory --host 0.0.0.0 --port 8000 --no-access-log --no-server-header --timeout-graceful-shutdown 20 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]
