FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATABASE_PATH=/data/acmp.sqlite3 PORT=8000
WORKDIR /app
COPY pyproject.toml LICENSE README.md ./
COPY acmp_connect ./acmp_connect
RUN pip install --no-cache-dir . && mkdir -p /data && chown 10001:10001 /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD ["python", "-m", "acmp_connect.healthcheck"]
ENTRYPOINT ["python", "-m", "acmp_connect.container_entrypoint"]
