FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV FASTEMBED_CACHE_PATH=/opt/fastembed_cache

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential git libpq-dev && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip

# Install dependencies first for layer caching (invalidated only when pyproject.toml changes)
COPY pyproject.toml .
RUN python3 -c "\
import tomllib, subprocess, sys; \
data = tomllib.load(open('pyproject.toml', 'rb')); \
deps = data['project']['dependencies']; \
subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-cache-dir'] + deps, check=True)"

# Pre-download fastembed BM25 model to avoid runtime network dependency
RUN python -c "from fastembed import SparseTextEmbedding; SparseTextEmbedding('Qdrant/bm25')"

# Copy source and install the local package (deps already installed above)
COPY . .
RUN pip install --no-cache-dir --no-deps .

EXPOSE 8000

CMD ["rag-api", "serve"]
