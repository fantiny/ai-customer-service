FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy everything first so setuptools can find src/
COPY pyproject.toml .
COPY src/ src/

# Install the package and all dependencies (including local-embed for fastembed)
RUN pip install --no-cache-dir -e ".[local-embed]"

# Copy remaining files (scripts, workspace, etc.)
COPY . .

# Create uploads directory
RUN mkdir -p /app/uploads

# Set a stable cache directory for fastembed so the model path is consistent
# between build time and runtime. The model is downloaded on first use.
# EMBEDDING_PROVIDER=local uses BAAI/bge-small-zh-v1.5 (512-dim, ~22MB ONNX).
ENV FASTEMBED_CACHE_DIR=/app/.fastembed_cache
RUN mkdir -p /app/.fastembed_cache

# Pre-download the embedding model at build time so the first request is fast.
# Uses --no-deps to avoid downloading build tools; falls back gracefully if the
# download fails (e.g., transient network error during CI/CD build).
RUN python -c "from fastembed import TextEmbedding; list(TextEmbedding('BAAI/bge-small-zh-v1.5').embed(['warmup']))" || \
    echo "WARNING: fastembed model pre-download failed — will download on first use"

EXPOSE 8000

CMD ["uvicorn", "src.ai_customer_service.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
