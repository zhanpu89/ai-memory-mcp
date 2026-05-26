#!/usr/bin/env python3
"""
AI Memory MCP Server - Service Manager
Usage: python service.py [start|stop|restart|status|log]
"""
import sys
import os
import subprocess
import time
import signal

HOME = os.path.expanduser("~")
# PID and log files go to home directory
AI_MEMORY_DIR = os.path.join(HOME, ".ai-memory")
PID_FILE = os.path.join(AI_MEMORY_DIR, "ai-memory.pid")
LOG_FILE = os.path.join(AI_MEMORY_DIR, "ai-memory.log")

# Ensure directory exists at module level
os.makedirs(AI_MEMORY_DIR, exist_ok=True)


def get_pid():
    """Get PID from file if exists and process is running"""
    if not os.path.exists(PID_FILE):
        return None
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        # Verify process is still running
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True
            )
            if str(pid) in result.stdout:
                return pid
        else:
            os.kill(pid, 0)  # Raises OSError if process doesn't exist
            return pid
    except (ValueError, OSError, ProcessLookupError):
        # Stale PID file
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    return None


def start(mode="http"):
    """Start MCP server in background
    
    Args:
        mode: "http" for HTTP mode, "stdio" for STDIO mode (default: http)
    """
    pid = get_pid()
    if pid:
        print(f"[WARN] Server is already running (PID: {pid})")
        return
    
    print(f"Starting AI Memory MCP Server ({mode.upper()} mode)...")
    print(f"Log file: {LOG_FILE}")
    
    # Build command args
    if sys.platform == "win32":
        scripts_dir = os.path.join(os.path.dirname(sys.executable), "Scripts")
        exe_path = os.path.join(scripts_dir, "ai-memory-mcp.exe")
        cmd = [exe_path]
    else:
        cmd = ["ai-memory-mcp"]
    
    if mode == "http":
        cmd.append("--http")
    
    # Start in background
    with open(LOG_FILE, "a", encoding="utf-8") as log_f:
        log_f.write("\n" + "="*50 + "\n")
        log_f.write(f"Server starting at {time.strftime('%Y-%m-%d %H:%M:%S')} ({mode} mode)\n")
        log_f.flush()
        
        if sys.platform == "win32":
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            
            # 构建环境变量：过滤可能导致干扰的变量
            clean_env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            # 屏蔽 Intel Fortran 运行时错误报告（避免产生误报）
            clean_env["FOR_DISABLE_CONSOLE_HANDLER"] = "TRUE"
            
            process = subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                cwd=HOME,
                env=clean_env
            )
        else:
            # Linux/macOS
            process = subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                cwd=HOME
            )
    
    pid = process.pid
    with open(PID_FILE, "w") as f:
        f.write(str(pid))
    
    # Wait a moment for startup
    time.sleep(2)
    
    # Verify still running
    if get_pid():
        print(f"\n[OK] Server started successfully!")
        print(f"PID: {pid}")
        print(f"Log: {LOG_FILE}")
        print(f"\nTo stop: python service.py stop")
        print(f"To view logs: python service.py log")
    else:
        print(f"\n[ERROR] Failed to start server. Check log:")
        print(LOG_FILE)
        sys.exit(1)


def stop():
    """Stop MCP server"""
    print("Stopping AI Memory MCP Server...")
    
    pid = get_pid()
    if pid:
        print(f"Found PID: {pid}")
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], 
                             capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
            print("[OK] Server stopped")
        except Exception as e:
            print(f"[ERROR] Failed to stop: {e}")
            sys.exit(1)
        finally:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
    else:
        print("[INFO] Server is not running")


def restart(mode="http"):
    """Restart MCP server"""
    print(f"Restarting AI Memory MCP Server ({mode.upper()} mode)...")
    stop()
    time.sleep(1)
    start(mode)


def status():
    """Check server status"""
    pid = get_pid()
    if pid:
        print(f"[RUNNING] Server is running (PID: {pid})")
        return True
    else:
        print("[STOPPED] Server is not running")
        return False


def log():
    """View server logs"""
    if not os.path.exists(LOG_FILE):
        print(f"No log file found: {LOG_FILE}")
        return
    
    print(f"Showing last 50 lines of server log:")
    print("=" * 50)
    
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
        for line in lines[-50:]:
            print(line, end="")
    print()


def main():
    commands = ["start", "stop", "restart", "status", "log"]
    
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print("=" * 50)
        print("  AI Memory MCP Server - Service Manager")
        print("=" * 50)
        print()
        print("Usage: python service.py <command> [options]")
        print()
        print("  start   [--stdio]      Start MCP server in background")
        print("  stop                   Stop running MCP server")
        print("  restart [--stdio]      Restart MCP server")
        print("  status                 Check server status")
        print("  log                    View server logs (last 50 lines)")
        print()
        print("Options:")
        print("  --stdio    Use STDIO mode (default: HTTP mode)")
        print()
        sys.exit(0)
    
    command = sys.argv[1]
    mode = "stdio" if "--stdio" in sys.argv else "http"
    
    if command == "start":
        start(mode)
    elif command == "stop":
        stop()
    elif command == "restart":
        restart(mode)
    elif command == "status":
        if not status():
            sys.exit(1)
    elif command == "log":
        log()


if __name__ == "__main__":
    main()
