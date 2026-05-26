# Docker Deployment Guide

## Quick Start

```bash
# 1. Clone repository
git clone https://github.com/your-org/ai-memory-mcp
cd ai-memory-mcp

# 2. (Optional) Pre-download model cache to avoid large image
python3 scripts/download_model_for_docker.py --output ./models

# 3. Build and start
docker compose up -d

# 4. View logs
docker compose logs -f

# 5. Access MCP endpoint
curl http://localhost:8000/mcp
```

---

## Architecture

### Image Size Optimization

The Docker image is kept **lightweight** (~200 MB) by:

1. **Multi-stage build** — build artifacts discarded in final image
2. **No embedded models** — model cache (~500 MB) mounted as external volume
3. **Optional vector search** — ChromaDB + sentence-transformers only installed via `INSTALL_VECTOR=true`
4. **Chinese mirror acceleration** — pip uses Tsinghua mirror, HuggingFace uses hf-mirror.com

### Volume Strategy

| Volume | Size | Purpose | Rebuild behavior |
|---|---|---|---|
| `ai_memory_data` | ~10 MB | SQLite DB + vector index | ✅ Persisted (Docker managed) |
| `./models` | ~500 MB | Embedding model cache | ✅ Persisted (host mount, read-only) |

**Key benefit:** Rebuilding the image does **not** re-download the 500 MB model.

---

## Build Options

### Option 1: Core-only (Lightweight, No Vector Search)

```bash
docker compose build
docker compose up -d
```

**Image size:** ~200 MB  
**Features:** SQLite storage, FTS5 full-text search, keyword search  
**Missing:** Semantic vector search

### Option 2: Full (With Vector Search)

```bash
# Download model to host first
python3 scripts/download_model_for_docker.py --output ./models

# Build with vector dependencies
docker compose build --build-arg INSTALL_VECTOR=true

# Start
docker compose up -d
```

**Image size:** ~700 MB (dependencies only; model is mounted externally)  
**Features:** All features including semantic vector search

---

## Pre-downloading Model (Recommended)

### Why?

- Keeps Docker image **small** (~200 MB core / ~700 MB full)
- Model cache (~500 MB) reused across image rebuilds
- Faster container startup (no download on first run)
- Use **Chinese mirror** for faster downloads

### How?

**Method 1: Using the helper script**

```bash
# Install sentence-transformers on host
pip install sentence-transformers

# Download model
python3 scripts/download_model_for_docker.py --output ./models

# The script automatically uses hf-mirror.com for China users
```

**Method 2: Manual download**

```bash
python3 << 'EOF'
import os
os.environ["SENTENCE_TRANSFORMERS_HOME"] = "./models"
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from sentence_transformers import SentenceTransformer
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
print("✅ Model downloaded to ./models")
EOF
```

**Method 3: Copy from existing installation**

```bash
# If you already have models in ~/.cache/huggingface
cp -r ~/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2 ./models/
```

---

## Configuration

### Environment Variables

Override defaults in `docker-compose.yml`:

```yaml
environment:
  AI_MEMORY_HOST: "0.0.0.0"          # Bind address
  AI_MEMORY_PORT: "8000"              # Listen port
  AI_MEMORY_DB_PATH: "/data/ai_memory.db"
  AI_MEMORY_MODEL_PATH: "/models"    # Model cache location
  HF_ENDPOINT: "https://hf-mirror.com"  # HuggingFace mirror
```

### Volume Mounts

```yaml
volumes:
  # Database + vector index (Docker-managed volume)
  - ai_memory_data:/data
  
  # Model cache (host directory, read-only)
  - ./models:/models:ro
  
  # Alternative: use absolute path
  - /opt/ai-memory/models:/models:ro
```

---

## Chinese Mirror Acceleration

### Pip (Python packages)

**Configured in Dockerfile:**
```dockerfile
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

**Alternative mirrors:**
- Tsinghua: `https://pypi.tuna.tsinghua.edu.cn/simple`
- Aliyun: `https://mirrors.aliyun.com/pypi/simple`
- Tencent: `https://mirrors.cloud.tencent.com/pypi/simple`

### HuggingFace (Model downloads)

**Configured via environment variable:**
```yaml
environment:
  HF_ENDPOINT: "https://hf-mirror.com"
```

**Alternative mirrors:**
- hf-mirror: `https://hf-mirror.com`
- ModelScope: `https://modelscope.cn` (requires code changes)

---

## Usage Examples

### Minimal Core-only Deployment

```bash
# Build without vector search
docker compose build

# Start
docker compose up -d

# Test
curl http://localhost:8000/mcp
```

### Full Deployment with Vector Search

```bash
# 1. Download model
python3 scripts/download_model_for_docker.py --output ./models

# 2. Build with vector support
docker compose build --build-arg INSTALL_VECTOR=true

# 3. Start
docker compose up -d

# 4. Verify vector search is enabled
docker compose logs | grep "向量库初始化成功"
```

### Production Deployment

```bash
# 1. Pre-download model to persistent location
mkdir -p /opt/ai-memory/models
python3 scripts/download_model_for_docker.py --output /opt/ai-memory/models

# 2. Update docker-compose.yml volume mount
#    - /opt/ai-memory/models:/models:ro

# 3. Build and deploy
docker compose build --build-arg INSTALL_VECTOR=true
docker compose up -d

# 4. Monitor
docker compose logs -f
```

---

## Troubleshooting

### Problem: Image too large

**Symptom:** Docker image > 1 GB

**Solution:**
- Verify models are **mounted** as external volume, not copied into image
- Check `AI_MEMORY_MODEL_PATH` points to `/models` (not `/data/models`)
- Rebuild with `--no-cache` to ensure fresh build

### Problem: Model download fails in container

**Symptom:** `No module named 'chromadb'` or model download timeout

**Solution 1:** Pre-download model on host (recommended)
```bash
python3 scripts/download_model_for_docker.py --output ./models
```

**Solution 2:** Use Chinese mirror
```yaml
environment:
  HF_ENDPOINT: "https://hf-mirror.com"
```

**Solution 3:** Disable vector search (core-only)
```yaml
args:
  INSTALL_VECTOR: "false"  # Default
```

### Problem: Permission denied on mounted model directory

**Symptom:** `PermissionError: [Errno 13] Permission denied: '/models/...'`

**Solution:** Ensure model directory is readable by container user
```bash
chmod -R 755 ./models
```

Or mount as read-only (already default in docker-compose.yml):
```yaml
- ./models:/models:ro
```

---

## Image Size Comparison

| Configuration | Image Size | Model Location | Total Disk |
|---|---|---|---|
| Core only (no vector) | ~200 MB | N/A | ~200 MB |
| Core + external model mount | ~200 MB | Host: `./models` (~500 MB) | ~700 MB |
| Full (vector in image) ❌ | ~1.2 GB | Embedded | ~1.2 GB |
| **Full + external mount** ✅ | ~700 MB | Host: `./models` (~500 MB) | ~1.2 GB |

**Recommendation:** Always use external model mount for production.

---

## Upgrading

```bash
# 1. Stop container
docker compose down

# 2. Pull latest code
git pull

# 3. Rebuild image
docker compose build --no-cache

# 4. Restart (volumes are preserved)
docker compose up -d

# Data in ai_memory_data volume and ./models is NOT affected
```

---

## Cleanup

```bash
# Stop and remove container
docker compose down

# Remove image
docker rmi ai-memory-mcp:latest

# Remove data volume (⚠️ deletes all session data)
docker volume rm ai-memory-mcp_ai_memory_data

# Remove model cache (can be re-downloaded)
rm -rf ./models
```
