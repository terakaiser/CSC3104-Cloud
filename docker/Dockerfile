FROM python:3.12.15-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    FLWR_TELEMETRY_ENABLED=0 FLWR_HOME=/home/flower/.flwr \
    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
WORKDIR /app
COPY docker/requirements.txt /app/docker/requirements.txt
RUN pip install --no-cache-dir --require-hashes --extra-index-url https://download.pytorch.org/whl/cpu -r docker/requirements.txt
COPY pyproject.toml /app/
COPY src /app/src
RUN pip install --no-cache-dir --no-deps . \
    && useradd --create-home --uid 10001 flower \
    && mkdir -p /data /results /state /home/flower/.flwr \
    && chown -R flower:flower /results /state /home/flower /app
COPY docker/flower-config.toml /home/flower/.flwr/config.toml
COPY docker/run-config.toml docker/check_health.py /app/docker/
USER 10001:10001
CMD ["flower-superlink", "--insecure", "--isolation", "subprocess"]
