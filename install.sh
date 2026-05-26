#!/bin/bash
set -e

echo "================================================"
echo "  AI Memory MCP Server - Unix Installer"
echo "================================================"
echo ""

# Check Python installation
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 is not installed or not in PATH"
    echo "Please install Python 3.10 or later:"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-pip"
    echo "  macOS: brew install python@3.12"
    echo "  CentOS/RHEL: sudo dnf install python3 python3-pip"
    exit 1
fi

# Check Python version
PYTHON_VERSION=$(python3 --version | awk '{print $2}')
echo "[INFO] Found Python: $PYTHON_VERSION"
echo ""

# Check version is >= 3.10
MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 10 ]); then
    echo "[ERROR] Python 3.10 or later is required"
    exit 1
fi

# Upgrade pip
echo "[INFO] Upgrading pip..."
python3 -m pip install --upgrade pip -q
echo ""

# Install package
echo "[INFO] Installing AI Memory MCP Server..."
python3 -m pip install -e .
if [ $? -ne 0 ]; then
    echo "[ERROR] Installation failed"
    exit 1
fi
echo ""

# Verify installation
echo "[INFO] Verifying installation..."
if ! python3 -m pip show ai-memory-mcp &> /dev/null; then
    echo "[ERROR] Installation verification failed"
    exit 1
fi

echo ""
echo "================================================"
echo "  Installation Complete!"
echo "================================================"
echo ""
echo "You can now run the MCP server using:"
echo "  ai-memory-mcp          (STDIO mode - default)"
echo "  ai-memory-mcp --http   (HTTP mode - for remote access)"
echo ""
echo "Or for development:"
echo "  python3 -m mcp_server.server"
echo ""
