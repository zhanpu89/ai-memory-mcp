# ── Stage 1: builder ─────────────────────────────────────────────────────────
FROM docker.1ms.run/library/python:3.12-slim AS builder

WORKDIR /build

# Configure pip to use Chinese mirror (Tsinghua)
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# Install build tools
RUN pip install --no-cache-dir build

# Copy only files needed for packaging
COPY pyproject.toml README.md MANIFEST.in ./
COPY src/ ./src/

# Build wheel
RUN python -m build --wheel --outdir /dist


# ── Stage 2: deps — rebuilt only when pyproject.toml/extras change ───────────
# This stage is cached independently. Code changes never bust this layer.
FROM docker.1ms.run/library/python:3.12-slim AS deps

RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

ARG INSTALL_VECTOR=false

# Copy only pyproject.toml to resolve dep names; actual wheel install comes next.
# We install deps separately so the heavy packages (chromadb, torch, etc.) are
# cached in their own layer and NOT invalidated by source code changes.
COPY pyproject.toml /tmp/pyproject.toml

# Install core deps (always cached unless pyproject.toml changes)
RUN pip install --no-cache-dir "mcp>=1.6.0" "python-dotenv>=1.0.0"

# Install vector deps (cached separately; only runs when INSTALL_VECTOR=true
# AND this layer is not already cached)
RUN if [ "$INSTALL_VECTOR" = "true" ]; then \
        pip install --no-cache-dir \
            "chromadb>=0.6.0" \
            "sentence-transformers>=3.0.0"; \
    fi


# ── Stage 3: runtime — only code changes here, rebuilds in seconds ────────────
FROM docker.1ms.run/library/python:3.12-slim

LABEL org.opencontainers.image.title="ai-memory-mcp"
LABEL org.opencontainers.image.description="Persistent AI session memory via MCP"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.source="https://github.com/zhanpu89/ai-memory-mcp"

RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# Create non-root user
RUN useradd --create-home --shell /bin/bash mcpuser

WORKDIR /app

# Copy installed packages from deps stage (cached layer, no re-download)
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Install the application wheel (only the package itself, deps already present)
# This layer is tiny (~50KB) and rebuilds in seconds on every code change.
COPY --from=builder /dist/*.whl /tmp/
RUN pip install --no-cache-dir --no-deps /tmp/*.whl && rm /tmp/*.whl

# Data volume — database and vector index live here
# Model cache is mounted separately (see docker-compose.yml)
RUN mkdir -p /data /models && chown -R mcpuser:mcpuser /data /models
VOLUME ["/data"]

# Environment defaults (can be overridden at runtime)
ENV AI_MEMORY_DB_PATH=/data/ai_memory.db \
    AI_MEMORY_MODEL_PATH=/models \
    AI_MEMORY_HOST=0.0.0.0 \
    AI_MEMORY_PORT=8000 \
    HF_ENDPOINT=https://hf-mirror.com

# Switch to non-root user
USER mcpuser

EXPOSE 8000

# Default: HTTP / streamable-HTTP transport
CMD ["ai-memory-mcp", "--http"]
