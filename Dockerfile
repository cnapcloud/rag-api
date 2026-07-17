FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1
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


FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# antiword: legacy .doc (MS Word 97-2003) parser, invoked via subprocess at runtime
# (pipeline/step/parser/doc.py). This is a genuine runtime dependency, unlike
# build-essential/git above.
RUN apt-get update && apt-get install -y --no-install-recommends antiword && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app /app

EXPOSE 8000

CMD ["rag-api", "serve"]
