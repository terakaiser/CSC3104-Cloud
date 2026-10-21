FROM python:3.12.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLWR_TELEMETRY_ENABLED=0 \
    FLWR_HOME=/tmp/flower \
    OMP_NUM_THREADS=1 \
    BANK_FL_DATA=/data \
    BANK_FL_OUTPUT=/results \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY app ./app
COPY experiments ./experiments
# uv.lock and the explicit CPU index in pyproject.toml avoid a CUDA dependency.
RUN pip install --no-cache-dir uv==0.11.6 \
    && uv sync --frozen --no-dev --no-cache --python /usr/local/bin/python \
    && groupadd --gid 10001 bankfl \
    && useradd --uid 10001 --gid bankfl --create-home bankfl
USER 10001:10001
CMD ["flower-superlink", "--insecure", "--serverappio-api-address", "127.0.0.1:9091", "--health-server-address", "0.0.0.0:9095"]
