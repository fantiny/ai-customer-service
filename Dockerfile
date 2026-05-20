FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
# Install production dependencies only (exclude dev group)
RUN pip install --no-cache-dir -e . --no-deps \
 && pip install --no-cache-dir \
    langgraph langgraph-checkpoint-redis langgraph-checkpoint-postgres \
    langchain-core langchain-community langchain-openai langchain-anthropic \
    fastapi "uvicorn[standard]" pydantic pydantic-settings \
    asyncpg pgvector "psycopg[binary,pool]" "redis[asyncio]" \
    langfuse rank-bm25 httpx "python-socketio[asyncio_client]" \
    python-jose python-multipart aiofiles pillow

COPY src/ src/

# Create uploads directory
RUN mkdir -p /app/uploads

EXPOSE 8000

CMD ["uvicorn", "src.ai_customer_service.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
