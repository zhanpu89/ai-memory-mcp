#!/usr/bin/env python3
"""
Pre-download embedding model to local cache for Docker volume mount.
This avoids embedding the large model (~500MB) directly in the Docker image.

Usage:
    python scripts/download_model_for_docker.py --output ./models

Then mount it in docker-compose.yml:
    volumes:
      - ./models:/models:ro
"""
import os
import sys
import argparse
from pathlib import Path


def download_model(output_dir: str):
    """Download sentence-transformers model to specified directory"""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("❌ sentence-transformers not installed")
        print("Install it with: pip install sentence-transformers")
        sys.exit(1)

    # Resolve output path
    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"📥 Downloading model to: {output_path}")
    print("   Model: sentence-transformers/all-MiniLM-L6-v2")
    print("   Size: ~80 MB (compressed), ~90 MB (on disk)")
    print()

    # Set cache directory
    os.environ["SENTENCE_TRANSFORMERS_HOME"] = str(output_path)
    os.environ["HF_HOME"] = str(output_path)
    
    # Use HuggingFace mirror for China users
    if os.getenv("HF_ENDPOINT") is None:
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        print(f"🌍 Using HuggingFace mirror: {os.environ['HF_ENDPOINT']}")
        print()

    try:
        # Download model
        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        
        print()
        print("✅ Model downloaded successfully!")
        print(f"📁 Location: {output_path}")
        print()
        print("Next steps:")
        print("  1. Mount this directory in docker-compose.yml:")
        print(f"     volumes:")
        print(f"       - {output_path}:/models:ro")
        print()
        print("  2. Set environment variable:")
        print("     AI_MEMORY_MODEL_PATH=/models")
        print()
        
    except Exception as e:
        print(f"❌ Download failed: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Pre-download embedding model for Docker deployment"
    )
    parser.add_argument(
        "--output",
        "-o",
        default="./models",
        help="Output directory for model cache (default: ./models)"
    )
    args = parser.parse_args()

    download_model(args.output)


if __name__ == "__main__":
    main()
