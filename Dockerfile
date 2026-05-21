FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy everything first so setuptools can find src/
COPY pyproject.toml .
COPY src/ src/

# Install the package and all dependencies
RUN pip install --no-cache-dir -e .

# Copy remaining files (scripts, workspace, etc.)
COPY . .

# Create uploads directory
RUN mkdir -p /app/uploads

# Pre-download local embedding model so first-request cold start is instant.
# EMBEDDING_PROVIDER=local uses BAAI/bge-small-zh-v1.5 (512-dim, ~22MB ONNX).
RUN python -c "from fastembed import TextEmbedding; list(TextEmbedding('BAAI/bge-small-zh-v1.5').embed(['warmup']))"

EXPOSE 8000

CMD ["uvicorn", "src.ai_customer_service.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
