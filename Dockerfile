FROM python:3.12-slim-bookworm AS builder

# UV_COMPILE_BYTECODE: ship .pyc for every installed dependency so the Dagster
# code server (and the API) don't recompile the whole import tree from source on
# each process start -- that cold compile is what blocks the gRPC health probe.
ENV UV_COMPILE_BYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# build-essential/git/libpq-dev: only needed to resolve and install Python deps in this
# stage. Discarded entirely once the runtime stage below copies out just the built venv.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential git libpq-dev && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install dependencies first for layer caching (invalidated only when pyproject.toml or uv.lock changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Copy source and install the local package (deps already installed above)
COPY src ./src
COPY migrations ./migrations
COPY settings.yaml ./
RUN uv sync --frozen --no-dev

# Precompile the first-party package too (installed from ./src, so UV_COMPILE_BYTECODE
# above only covers the .venv). compileall writes .pyc regardless of any -B / env flag.
RUN python -m compileall -q -j0 /app/src


FROM python:3.12-slim-bookworm AS runtime

# No PYTHONDONTWRITEBYTECODE here: the build already ships .pyc, and allowing writes
# lets any cache miss self-heal on first import instead of recompiling every start.
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# antiword: legacy .doc (MS Word 97-2003) parser, invoked via subprocess at runtime
# (pipeline/steps/parser/doc.py). This is a genuine runtime dependency, unlike
# build-essential/git above.
RUN apt-get update && apt-get install -y --no-install-recommends antiword && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app /app

EXPOSE 8000

CMD ["rag-api", "serve"]
