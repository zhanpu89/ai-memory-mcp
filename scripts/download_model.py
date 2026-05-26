import os

# 设置 HuggingFace 镜像源
# os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com/sentence-transformers/all-MiniLM-L6-v2")
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from huggingface_hub import snapshot_download

# 获取当前脚本所在目录的父目录
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)  # 上一级目录

model_id = "sentence-transformers/all-MiniLM-L6-v2"
# 基于项目根目录生成模型缓存路径
local_dir = os.path.join(project_root, "models", "models--sentence-transformers--all-MiniLM-L6-v2", "snapshots", "c9745ed1d9f207416be6d2e6f8de32d1f16199bf")

print(f"正在从 hf-mirror.com 下载模型: {model_id}")
print(f"保存路径: {local_dir}")

os.makedirs(local_dir, exist_ok=True)

try:
    snapshot_download(
        repo_id=model_id,
        local_dir=local_dir,
        local_dir_use_symlinks=False,
        resume_download=True,
    )
    print(f"模型下载完成！")
    print(f"模型路径: {local_dir}")

    files = os.listdir(local_dir)
    print(f"下载的文件列表:")
    for f in files:
        file_path = os.path.join(local_dir, f)
        size = os.path.getsize(file_path)
        print(f"  {f}: {size:,} bytes")

except Exception as e:
    print(f"下载失败: {e}")
