# ── Stage 0: deps — 版本固定，永久缓存 ──────────────────────────────────────────
FROM docker.1ms.run/library/python:3.12-slim AS deps

RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --no-cache-dir setuptools wheel
RUN pip install --no-cache-dir "mcp>=1.6.0" "python-dotenv>=1.0.0"


# ── Stage 1: vector deps (heavy ~4 GB，仅 ai-memory 需要) ─────────────────────
FROM deps AS vector-deps
RUN pip install --no-cache-dir "chromadb>=0.6.0" "sentence-transformers>=3.0.0"


# ── Stage 2: web deps（轻量 ~200 MB，仅 ai-memory-web 需要）───────────────────
FROM deps AS web-deps
RUN pip install --no-cache-dir \
    "fastapi>=0.109.0" \
    "uvicorn[standard]>=0.27.0" \
    "jinja2>=3.1.0"


# ── Stage 3: runtime 基座（代码变更只重建此层之后的 stage）────────────────────
FROM docker.1ms.run/library/python:3.12-slim AS runtime-base

RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

RUN useradd --create-home --shell /bin/bash mcpuser
WORKDIR /app

COPY pyproject.toml README.md MANIFEST.in ./
COPY src/ ./src/
COPY web_panel/ ./web_panel/

RUN mkdir -p /data /models && chown -R mcpuser:mcpuser /data /models
VOLUME ["/data"]

ENV AI_MEMORY_DB_PATH=/data/ai_memory.db \
    AI_MEMORY_MODEL_PATH=/models \
    AI_MEMORY_HOST=0.0.0.0 \
    AI_MEMORY_PORT=8000 \
    AI_MEMORY_WEB_HOST=0.0.0.0 \
    AI_MEMORY_WEB_PORT=8080 \
    HF_ENDPOINT=https://hf-mirror.com

EXPOSE 8000 8080


# ── Target: ai-memory — MCP 服务器（带向量支持）───────────────────────────────
FROM runtime-base AS ai-memory

COPY --from=vector-deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=vector-deps /usr/local/bin /usr/local/bin

RUN pip install --no-cache-dir --no-build-isolation --no-deps -e .

LABEL org.opencontainers.image.title="ai-memory-mcp"
LABEL org.opencontainers.image.description="Persistent AI session memory via MCP"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.source="https://github.com/zhanpu89/ai-memory-mcp"

USER mcpuser
CMD ["ai-memory-mcp", "--http"]


# ── Target: ai-memory-web — Web 管理面板（无向量）────────────────────────────
FROM runtime-base AS ai-memory-web

COPY --from=web-deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=web-deps /usr/local/bin /usr/local/bin

RUN pip install --no-cache-dir --no-build-isolation --no-deps -e .

USER mcpuser
CMD ["ai-memory-web"]
