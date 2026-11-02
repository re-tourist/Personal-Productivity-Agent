FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PPA_DATA_DIR=/app/.ppa-data PPA_ENABLE_LIVE_QWEN=0
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --no-cache-dir .
EXPOSE 8000
# Bind the Docker *published port* to 127.0.0.1 on the host.
CMD ["uvicorn", "productivity_agent.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
