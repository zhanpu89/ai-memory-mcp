# ── Stage 1: dependencies — cached except when pyproject.toml / build-args change ──
FROM docker.1ms.run/library/python:3.12-slim AS deps

RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# Build-system tools needed by --no-build-isolation in the runtime stage
RUN pip install --no-cache-dir setuptools wheel

ARG INSTALL_VECTOR=false
ARG INSTALL_WEB=false

# Core runtime dependencies
RUN pip install --no-cache-dir "mcp>=1.6.0" "python-dotenv>=1.0.0"

# Vector dependencies (heavy — cached separately; only installed when requested)
RUN if [ "$INSTALL_VECTOR" = "true" ]; then \
        pip install --no-cache-dir \
            "chromadb>=0.6.0" \
            "sentence-transformers>=3.0.0"; \
    fi

# Web dependencies (cached separately; only installed when requested)
RUN if [ "$INSTALL_WEB" = "true" ]; then \
        pip install --no-cache-dir \
            "fastapi>=0.109.0" \
            "uvicorn[standard]>=0.27.0" \
            "jinja2>=3.1.0"; \
    fi


# ── Stage 2: runtime — code changes rebuild in ~5 seconds ──
FROM docker.1ms.run/library/python:3.12-slim

LABEL org.opencontainers.image.title="ai-memory-mcp"
LABEL org.opencontainers.image.description="Persistent AI session memory via MCP"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.source="https://github.com/zhanpu89/ai-memory-mcp"

RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

RUN useradd --create-home --shell /bin/bash mcpuser

WORKDIR /app

# Copy pre-installed packages from deps stage (cached — never redownloads)
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy source code (only this layer is rebuilt on code changes)
COPY pyproject.toml README.md MANIFEST.in ./
COPY src/ ./src/
COPY web_panel/ ./web_panel/

# Install the package itself — no download, no build isolation, no deps resolution
RUN pip install --no-cache-dir --no-build-isolation --no-deps -e .

# Data volume
RUN mkdir -p /data /models && chown -R mcpuser:mcpuser /data /models
VOLUME ["/data"]

ENV AI_MEMORY_DB_PATH=/data/ai_memory.db \
    AI_MEMORY_MODEL_PATH=/models \
    AI_MEMORY_HOST=0.0.0.0 \
    AI_MEMORY_PORT=8000 \
    AI_MEMORY_WEB_HOST=0.0.0.0 \
    AI_MEMORY_WEB_PORT=8080 \
    HF_ENDPOINT=https://hf-mirror.com

USER mcpuser

EXPOSE 8000 8080

CMD ["ai-memory-mcp", "--http"]
