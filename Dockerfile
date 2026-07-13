FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .
EXPOSE 8000
CMD exec uvicorn aegis_llm_gateway.api.main:app --host 0.0.0.0 --port ${PORT:-8000}
