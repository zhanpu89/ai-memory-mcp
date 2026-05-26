# AI Memory MCP Server - 安装与配置指南

## 快速开始

### 1. 安装

```bash
# 克隆或下载项目
cd d:\IdeaProjects\mcp__ai_memory   # Windows
# cd ~/projects/mcp__ai_memory     # macOS/Linux

# 可编辑安装（推荐，源码修改后自动生效）
pip install -e .
```

### 2. 首次启动

```bash
# 后台启动 HTTP 服务（默认）
python service.py start

# 查看状态
python service.py status

# 查看日志
python service.py log
```

首次启动会自动：
- 创建用户目录 `~/.ai-memory/`
- 下载 Embedding 模型（约 80MB，国内自动使用镜像源）
- 初始化数据库

---

## 目录结构

```
~/.ai-memory/                          # 用户数据目录（家目录下）
├── .env                               # 配置文件（可选）
├── ai_memory.db                        # SQLite 数据库
├── ai-memory.pid                      # 服务进程 PID
├── ai-memory.log                      # 服务运行日志
├── vector_db/                          # 向量数据库（ChromaDB）
└── models/                             # 嵌入模型缓存
    └── models--sentence-transformers--all-MiniLM-L6-v2/
        └── snapshots/
            └── c9745ed1d9f207416be6d2e6f8de32d1f16199bf/

项目目录/
├── .env                               # 项目配置（可覆盖家目录配置）
├── service.py                         # 服务管理脚本
├── src/mcp_server/                    # 源码
├── scripts/download_model.py          # 手动下载模型脚本
└── model_cache/                       # 项目目录模型缓存（可选）
```

---

## 配置

### 配置文件加载优先级

服务启动时从**家目录**（`~` 或 `%USERPROFILE%`）运行，配置文件加载顺序：

1. **家目录配置**：`~/.ai-memory/.env`（基础配置）
2. **当前目录配置**：如果当前目录有 `.env`，可覆盖家目录配置
3. **系统环境变量**：最高优先级

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `AI_MEMORY_DB_PATH` | `~/.ai-memory/ai_memory.db` | 数据库路径 |
| `AI_MEMORY_MODEL_PATH` | `~/.ai-memory/models` | 模型缓存根路径 |

### 创建家目录配置

在 `~/.ai-memory/.env` 中创建：

```env
# 数据库路径（可选，不设置时使用默认值）
AI_MEMORY_DB_PATH=C:\Users\你的用户名\.ai-memory\ai_memory.db

# 模型路径（可选，不设置时使用默认值）
AI_MEMORY_MODEL_PATH=C:\Users\你的用户名\.ai-memory\models
```

**Windows 路径示例**：
```env
AI_MEMORY_DB_PATH=C:\Users\Administrator\.ai-memory\ai_memory.db
AI_MEMORY_MODEL_PATH=C:\Users\Administrator\.ai-memory\models
```

**macOS/Linux 路径示例**：
```env
AI_MEMORY_DB_PATH=/Users/username/.ai-memory/ai_memory.db
AI_MEMORY_MODEL_PATH=/Users/username/.ai-memory/models
```

### 迁移历史数据

如果你之前在项目目录下有数据库和模型数据，可以迁移到家目录：

**Windows (PowerShell)**：
```powershell
# 创建家目录数据目录
mkdir "$env:USERPROFILE\.ai-memory"

# 复制数据库
Copy-Item "d:\IdeaProjects\mcp__ai_memory\ai_memory.db" -Destination "$env:USERPROFILE\.ai-memory\ai_memory.db"

# 复制向量数据库
Copy-Item "d:\IdeaProjects\mcp__ai_memory\vector_db" -Destination "$env:USERPROFILE\.ai-memory\vector_db" -Recurse

# 复制模型
Copy-Item "d:\IdeaProjects\mcp__ai_memory\model_cache" -Destination "$env:USERPROFILE\.ai-memory\models" -Recurse
```

**macOS/Linux**：
```bash
mkdir -p ~/.ai-memory
cp /path/to/project/ai_memory.db ~/.ai-memory/
cp -r /path/to/project/vector_db ~/.ai-memory/
cp -r /path/to/project/model_cache/* ~/.ai-memory/models/
```

---

## 服务管理

### 基本命令

```bash
# 启动服务（后台运行，默认 HTTP 模式）
python service.py start

# 启动 STDIO 模式
python service.py start --stdio

# 停止服务
python service.py stop

# 重启服务（保持当前模式）
python service.py restart

# 重启为 STDIO 模式
python service.py restart --stdio

# 查看服务状态
python service.py status

# 查看最近 50 行日志
python service.py log
```

### 服务模式说明

| 模式 | 用途 | 说明 |
|------|------|------|
| HTTP | MCP 客户端远程连接 | 监听 `http://localhost:8000/mcp` |
| STDIO | IDE 集成（VS Code / Cursor / Claude Desktop） | 标准输入输出通信 |

### 日志位置

- **Windows**: `C:\Users\Administrator\.ai-memory\ai-memory.log`
- **macOS/Linux**: `~/.ai-memory/ai-memory.log`

---

## MCP 客户端配置

### Claude Desktop

在配置文件中添加：
```json
{
  "mcpServers": {
    "ai-memory": {
      "command": "ai-memory-mcp"
    }
  }
}
```

### VS Code / Cursor

在 MCP 设置中添加：
```json
{
  "mcpServers": {
    "ai-memory": {
      "command": "ai-memory-mcp"
    }
  }
}
```

### HTTP 模式（远程连接）

```json
{
  "mcpServers": {
    "ai-memory": {
      "command": "ai-memory-mcp",
      "args": ["--http"],
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

---

## 升级

当你更新了源码后，需要重新安装使更改生效：

```bash
# 1. 停止服务
python service.py stop

# 2. 重新安装（可编辑安装，源码修改自动生效）
pip install -e . --force-reinstall --no-deps

# 3. 重启服务
python service.py start

# 4. 验证
python service.py log
```

> **注意**：如果 `pip install` 报权限错误（`[WinError 5] 拒绝访问`），请使用管理员 PowerShell 执行，或关闭杀毒软件后重试。

### 数据库自动迁移

新版本如果修改了数据库结构，服务启动时会**自动迁移**旧数据库，无需手动操作。迁移内容包括：
- 添加缺失的列（如 `project_name`、`branch_name`）
- 更新状态约束（如添加 `pending` 状态）

---

## 验证安装

```bash
# 检查安装
pip show ai-memory-mcp

# 验证命令可用
ai-memory-mcp --help

# 测试服务启动
python service.py start
python service.py status
python service.py log
```

---

## 故障排除

### 问题：服务启动失败

```bash
# 查看日志
python service.py log

# 检查端口是否被占用
netstat -ano | findstr :8000    # Windows
lsof -i :8000                   # macOS/Linux

# 杀掉占用进程
taskkill /PID <PID> /F          # Windows
kill -9 <PID>                   # macOS/Linux
```

### 问题：模型下载失败

国内网络可能无法直接访问 HuggingFace，服务会自动使用镜像源 `hf-mirror.com`。如果仍然失败：

```bash
# 手动下载模型
python scripts/download_model.py
```

### 问题：权限不足

```bash
# 使用用户安装
pip install --user -e .

# 或使用虚拟环境
python -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows
pip install -e .
```

### 问题：旧数据库不兼容

服务启动时会自动检测并迁移旧版本数据库。如果迁移失败，日志会显示详细错误信息。

---

## 卸载

```bash
# 停止服务
python service.py stop

# 卸载包
pip uninstall ai-memory-mcp

# 删除用户数据（可选）
rm -rf ~/.ai-memory             # macOS/Linux
Remove-Item -Recurse "$env:USERPROFILE\.ai-memory"  # Windows
```
