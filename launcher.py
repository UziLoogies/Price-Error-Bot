"""
Desktop launcher for Price Error Bot with windowed UI.

This script:
1. Checks if Docker containers are running (starts them if not)
2. Starts the FastAPI server in a background thread
3. Opens a native window with the dashboard UI
4. Handles graceful shutdown when the window is closed
"""

import asyncio
import ctypes
import logging
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path
from typing import List, Optional

# Configuration
PORT = 8001
HOST = "127.0.0.1"
URL = f"http://{HOST}:{PORT}"
WINDOW_TITLE = "Price Error Bot"
WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 900
MIN_WIDTH = 1024
MIN_HEIGHT = 768

# Server state
server_started = threading.Event()
shutdown_requested = threading.Event()

# At most one MessageBox per run for startup/fatal errors
_startup_messagebox_shown = False

# Global logger (initialized after excepthook)
logger = None


def get_project_root() -> Path:
    """Get the project root directory."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def global_exception_handler(exc_type, exc_value, exc_traceback):
    """Global exception handler for unhandled exceptions. Uses only stderr (no logger)."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    try:
        error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        print(f"\n{'='*60}", file=sys.stderr, flush=True)
        print("UNHANDLED EXCEPTION:", file=sys.stderr, flush=True)
        print(f"{'='*60}", file=sys.stderr, flush=True)
        print(error_msg, file=sys.stderr, flush=True)
        print(f"{'='*60}\n", file=sys.stderr, flush=True)
    except Exception:
        print(f"FATAL: Unhandled {exc_type.__name__}: {exc_value}", file=sys.stderr, flush=True)
    sys.exit(1)


def thread_exception_handler(args):
    """Handle exceptions in threads. Uses only stderr (no logger)."""
    print(
        f"Unhandled exception in thread: {args.exc_type.__name__}: {args.exc_value}",
        file=sys.stderr,
        flush=True,
    )


# Set excepthook first, before any project imports or logger init
sys.excepthook = global_exception_handler
threading.excepthook = thread_exception_handler


def safe_configure_logging():
    """
    Safely configure logging. Imports setup_logging lazily (no top-level src import).
    Falls back to basic logging if src.logging_config or src.config fails.
    """
    try:
        from src.logging_config import setup_logging
        project_root = get_project_root()
        setup_logging(base_dir=project_root)
        return logging.getLogger("launcher")
    except Exception as e:
        try:
            logs_dir = get_project_root() / "logs"
            logs_dir.mkdir(exist_ok=True)
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                handlers=[
                    logging.StreamHandler(sys.stdout),
                    logging.FileHandler(logs_dir / "launcher.log", mode='a'),
                ],
            )
            log = logging.getLogger("launcher")
            log.warning("Failed to setup advanced logging, using basic logging: %s", e)
            return log
        except Exception:
            logging.basicConfig(level=logging.INFO)
            return logging.getLogger("launcher")


# Initialize logger after excepthook
try:
    logger = safe_configure_logging()
except Exception:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("launcher")


def show_startup_error_messagebox(
    title: str,
    message: str,
    suggestions: Optional[List[str]] = None,
) -> None:
    """
    Show a startup/fatal error via ctypes MessageBoxW only. No webview.
    At most one MessageBox per run; if already shown, log/print and return.
    """
    global _startup_messagebox_shown
    if _startup_messagebox_shown:
        if logger is not None:
            logger.error("%s: %s", title, message)
            if suggestions:
                logger.error("Suggestions: %s", ", ".join(suggestions))
        print(f"\nERROR: {title}\n{message}\n", flush=True)
        return
    _startup_messagebox_shown = True

    parts = [message]
    if suggestions:
        parts.append("\n\nSuggestions:")
        for s in suggestions:
            parts.append(f"\n  \u2022 {s}")
    text = "".join(parts)

    try:
        # MB_OK | MB_ICONERROR = 0x10
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
    except Exception as e:
        if logger is not None:
            logger.error("Failed to show MessageBox: %s", e)
        print(f"\n{'='*60}", flush=True)
        print(f"ERROR: {title}", flush=True)
        print(f"{'='*60}", flush=True)
        print(message, flush=True)
        if suggestions:
            print("\nSuggestions:", flush=True)
            for i, s in enumerate(suggestions, 1):
                print(f"  {i}. {s}", flush=True)
        print(f"{'='*60}\n", flush=True)


def check_docker_daemon() -> bool:
    """
    Check if Docker daemon is running (more robust check).
    
    Returns True if Docker is running and accessible, False otherwise.
    """
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return True
        
        # Check for common error messages
        error_output = result.stderr.lower()
        if "cannot connect" in error_output or "is the docker daemon running" in error_output:
            logger.error("Docker daemon is not running")
            return False
        
        logger.warning(f"Docker check returned non-zero: {result.stderr}")
        return False
    except FileNotFoundError:
        logger.error("Docker command not found. Is Docker Desktop installed?")
        return False
    except subprocess.TimeoutExpired:
        logger.error("Docker check timed out")
        return False
    except Exception as e:
        logger.error(f"Docker check failed: {e}")
        return False


def check_docker_running() -> bool:
    """Check if Docker daemon is running (alias for compatibility)."""
    return check_docker_daemon()


def check_container_running(container_name: str) -> bool:
    """Check if a specific Docker container is running."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return container_name in result.stdout
    except Exception as e:
        logger.warning(f"Container check failed for {container_name}: {e}")
        return False


def verify_container_healthy(container_name: str, max_wait: int = 30) -> bool:
    """
    Verify container is healthy and ready (not just started).
    
    Checks container health status and waits for it to be ready.
    """
    start_time = time.time()
    logger.info(f"Verifying container {container_name} is healthy...")
    
    while time.time() - start_time < max_wait:
        try:
            # Check if container exists and get its state
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Status}}", container_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                logger.debug(f"Container {container_name} not found yet")
                time.sleep(2)
                continue
            
            status = result.stdout.strip()
            
            if status == "running":
                # Check health status if health check is configured
                health_result = subprocess.run(
                    ["docker", "inspect", "--format", "{{.State.Health.Status}}", container_name],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if health_result.returncode == 0:
                    health_status = health_result.stdout.strip()
                    if health_status in ["healthy", "none"]:
                        # "none" means no health check configured, which is fine
                        logger.info(f"Container {container_name} is ready")
                        return True
                    elif health_status == "starting":
                        logger.debug(f"Container {container_name} health check is starting...")
                    else:
                        logger.warning(f"Container {container_name} health status: {health_status}")
                else:
                    # No health check configured, just check if running
                    logger.info(f"Container {container_name} is running (no health check)")
                    return True
            elif status in ["restarting", "starting"]:
                logger.debug(f"Container {container_name} is {status}...")
            else:
                logger.warning(f"Container {container_name} status: {status}")
            
            time.sleep(2)
        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout checking container {container_name}")
            time.sleep(2)
        except Exception as e:
            logger.debug(f"Error checking container health: {e}")
            time.sleep(2)
    
    logger.warning(f"Container {container_name} did not become healthy within {max_wait} seconds")
    return False


def start_docker_containers() -> bool:
    """Start PostgreSQL and Redis containers with health verification."""
    project_root = get_project_root()
    
    try:
        logger.info("Starting Docker containers...")
        result = subprocess.run(
            ["docker", "compose", "up", "-d", "postgres", "redis"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            logger.error(f"Failed to start containers: {result.stderr}")
            return False
        
        # Wait for containers to be healthy
        logger.info("Waiting for containers to be ready...")
        
        # Verify PostgreSQL is ready
        postgres_ready = verify_container_healthy("price_bot_postgres", max_wait=30)
        if not postgres_ready:
            logger.warning("PostgreSQL container may not be fully ready")
        
        # Verify Redis is ready
        redis_ready = verify_container_healthy("price_bot_redis", max_wait=20)
        if not redis_ready:
            logger.warning("Redis container may not be fully ready")
        
        # Both should be ready, but continue if at least one is
        if postgres_ready and redis_ready:
            logger.info("All containers are ready")
            return True
        elif postgres_ready or redis_ready:
            logger.warning("Some containers may not be fully ready, but continuing...")
            return True
        else:
            logger.error("Containers failed to become ready")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("Timeout starting Docker containers")
        return False
    except Exception as e:
        logger.error(f"Failed to start Docker containers: {e}")
        return False


def ensure_docker_ready() -> bool:
    """
    Ensure Docker and required containers are running and healthy.
    
    Enhanced version with better error handling and health checks.
    """
    # Step 1: Check Docker daemon
    logger.info("Checking Docker daemon...")
    if not check_docker_daemon():
        logger.error("Docker daemon is not running. Please start Docker Desktop.")
        return False
    
    # Step 2: Check if containers are running
    postgres_running = check_container_running("price_bot_postgres")
    redis_running = check_container_running("price_bot_redis")
    
    logger.info(f"Container status - PostgreSQL: {'running' if postgres_running else 'stopped'}, "
                f"Redis: {'running' if redis_running else 'stopped'}")
    
    # Step 3: Start containers if needed
    if not postgres_running or not redis_running:
        logger.info("Starting required containers...")
        if not start_docker_containers():
            return False
    
    # Step 4: Verify containers are healthy
    logger.info("Verifying container health...")
    postgres_healthy = verify_container_healthy("price_bot_postgres", max_wait=10)
    redis_healthy = verify_container_healthy("price_bot_redis", max_wait=10)
    
    if postgres_healthy and redis_healthy:
        logger.info("All Docker containers are ready and healthy")
        return True
    elif postgres_healthy or redis_healthy:
        logger.warning("Some containers may not be fully healthy, but continuing...")
        return True
    else:
        logger.error("Containers failed health checks")
        return False


def check_server_ready() -> bool:
    """Check if the FastAPI server is ready."""
    try:
        urllib.request.urlopen(URL, timeout=2)
        return True
    except Exception:
        return False


def is_port_in_use(port: int) -> bool:
    """
    Check if port is in LISTEN state (like PowerShell Get-NetTCPConnection).
    
    Uses multiple methods for reliability:
    1. Try to bind to the port (most reliable)
    2. Use psutil to check network connections
    """
    # Method 1: Try to bind to the port (most reliable)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(('127.0.0.1', port))
        sock.close()
        return False  # Port is free
    except OSError:
        sock.close()
        # Port might be in use, verify with psutil
    
    # Method 2: Use psutil to find processes on port (if available)
    try:
        import psutil
        for conn in psutil.net_connections(kind='inet'):
            if conn.status == psutil.CONN_LISTEN:
                if hasattr(conn, 'laddr') and conn.laddr and conn.laddr.port == port:
                    return True
    except (ImportError, psutil.AccessDenied, AttributeError, Exception) as e:
        logger.debug(f"psutil check failed: {e}")
        # If psutil fails, assume port is in use (from bind failure)
        return True
    
    return True  # Assume in use if bind failed


def find_processes_on_port(port: int) -> List[int]:
    """Find all process IDs using the specified port."""
    pids = []
    try:
        import psutil
        for conn in psutil.net_connections(kind='inet'):
            if conn.status == psutil.CONN_LISTEN:
                if hasattr(conn, 'laddr') and conn.laddr and conn.laddr.port == port:
                    if hasattr(conn, 'pid') and conn.pid:
                        pids.append(conn.pid)
    except (ImportError, psutil.AccessDenied, AttributeError) as e:
        logger.debug(f"Failed to find processes on port: {e}")
        # Fallback: try to find by iterating all processes
        try:
            import psutil
            for proc in psutil.process_iter(['pid', 'connections']):
                try:
                    connections = proc.info.get('connections') or []
                    for conn in connections:
                        if (hasattr(conn, 'status') and conn.status == psutil.CONN_LISTEN and
                            hasattr(conn, 'laddr') and conn.laddr and conn.laddr.port == port):
                            pids.append(proc.info['pid'])
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, AttributeError):
                    continue
        except Exception as e:
            logger.debug(f"Fallback process search failed: {e}")
    
    return list(set(pids))  # Remove duplicates


def kill_processes_on_port(port: int, max_retries: int = 3) -> bool:
    """
    Kill all processes using the specified port with retry logic.
    
    Returns True if port was freed, False otherwise.
    """
    killed_any = False
    
    for attempt in range(max_retries):
        pids = find_processes_on_port(port)
        
        if not pids:
            # Port is free
            if killed_any:
                logger.info(f"Port {port} is now free after killing processes")
            return True
        
        logger.info(f"Found {len(pids)} process(es) on port {port} (attempt {attempt + 1}/{max_retries})")
        
        try:
            import psutil
            for pid in pids:
                try:
                    proc = psutil.Process(pid)
                    proc_name = proc.name()
                    logger.info(f"Killing process {proc_name} (PID: {pid})...")
                    proc.terminate()  # Try graceful termination first
                    killed_any = True
                except psutil.NoSuchProcess:
                    # Process already gone
                    pass
                except psutil.AccessDenied:
                    # Try force kill
                    try:
                        proc.kill()
                        logger.warning(f"Force killed process {pid}")
                        killed_any = True
                    except Exception as e:
                        logger.warning(f"Could not kill process {pid}: {e}")
                except Exception as e:
                    logger.warning(f"Error killing process {pid}: {e}")
            
            # Wait a bit for processes to terminate
            if killed_any:
                time.sleep(1)
                
        except ImportError:
            # psutil not available, fallback to PowerShell
            logger.warning("psutil not available, using PowerShell fallback")
            try:
                subprocess.run(
                    [
                        "powershell", "-Command",
                        f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | "
                        f"ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }}"
                    ],
                    capture_output=True,
                    timeout=10
                )
                killed_any = True
                time.sleep(1)
            except Exception as e:
                logger.error(f"PowerShell fallback failed: {e}")
                return False
    
    # Final check
    if is_port_in_use(port):
        logger.error(f"Port {port} is still in use after {max_retries} attempts")
        return False
    
    return True


def wait_for_port_free(port: int, timeout_seconds: int = 10) -> bool:
    """
    Wait for port to become available with timeout.
    
    Returns True if port is free, False if timeout exceeded.
    """
    start_time = time.time()
    elapsed = 0
    
    while elapsed < timeout_seconds:
        if not is_port_in_use(port):
            if elapsed > 0:
                logger.info(f"Port {port} is now free (waited {elapsed:.1f}s)")
            return True
        
        time.sleep(0.5)
        elapsed = time.time() - start_time
        
        if int(elapsed) % 2 == 0 and int(elapsed) > 0:
            logger.info(f"Waiting for port {port} to be free... ({int(elapsed)}s/{timeout_seconds}s)")
    
    logger.error(f"Port {port} did not become free within {timeout_seconds} seconds")
    return False


def kill_existing_server():
    """Kill any existing process on the server port (enhanced version)."""
    if not is_port_in_use(PORT):
        logger.debug(f"Port {PORT} is already free")
        return
    
    logger.info(f"Port {PORT} is in use, attempting to free it...")
    
    if kill_processes_on_port(PORT, max_retries=3):
        # Wait for port to be confirmed free
        if wait_for_port_free(PORT, timeout_seconds=10):
            logger.info(f"Port {PORT} successfully freed")
        else:
            logger.warning(f"Port {PORT} may still be in use")
    else:
        logger.error(f"Failed to free port {PORT}")


def start_server():
    """Start the FastAPI server in a background thread."""
    
    def run_server():
        try:
            # Import here to avoid import errors before dependencies are ready
            import uvicorn
            from src.main import app
            
            config = uvicorn.Config(
                app,
                host=HOST,
                port=PORT,
                log_level="info",
                access_log=True,
                loop="asyncio"
            )
            server = uvicorn.Server(config)
            
            # Signal that server is starting
            server_started.set()
            
            # Run until shutdown is requested
            asyncio.run(server.serve())
            
        except ImportError as e:
            if logger is not None:
                logger.error(f"Failed to import server dependencies: {e}", exc_info=True)
            server_started.set()  # Unblock main thread
            raise  # Re-raise to be caught by main()
        except Exception as e:
            if logger is not None:
                logger.error(f"Server error: {e}", exc_info=True)
            server_started.set()  # Unblock main thread even on error
            # Don't re-raise - let main() handle the server startup failure
    
    # Kill any existing server on the port
    kill_existing_server()
    time.sleep(1)
    
    # Start server in daemon thread
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    
    # Wait for server to be ready
    logger.info("Starting server...")
    max_attempts = 60  # 30 seconds max
    
    for i in range(max_attempts):
        if check_server_ready():
            logger.info(f"Server is ready at {URL}")
            return True
        time.sleep(0.5)
        
        if i % 10 == 0 and i > 0:
            logger.info(f"Still waiting for server... ({i // 2}s)")
    
    logger.error("Server failed to start within timeout")
    return False


def on_closed():
    """Handle window close event."""
    if logger is not None:
        logger.info("Window closed. Shutting down...")
    shutdown_requested.set()


def print_progress(step: str, message: str):
    """Print progress message with formatting."""
    if logger is not None:
        logger.info(f"[{step}] {message}")
    # Also print to console for visibility
    print(f"[{step}] {message}", flush=True)


def check_webview2_available() -> bool:
    """Check if WebView2 Runtime is available on this system."""
    try:
        import winreg
        # Check for WebView2 in registry
        key_paths = [
            r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
            r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        ]
        for key_path in key_paths:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path):
                    return True
            except FileNotFoundError:
                continue
        return False
    except Exception:
        return True  # Assume available if check fails


def main():
    """Main entry point."""
    global logger
    
    try:
        # Ensure logger is initialized
        if logger is None:
            logger = safe_configure_logging()

        print("\n" + "="*60)
        print("  Price Error Bot Desktop Launcher")
        print("="*60 + "\n")
        if logger is not None:
            logger.info("="*60)
            logger.info("Price Error Bot Desktop Launcher")
            logger.info("="*60)

        # Step 1: Ensure Docker is ready
        print_progress("Step 1/4", "Checking Docker...")
        if not ensure_docker_ready():
            show_startup_error_messagebox(
                "Startup Failed",
                "Docker daemon not available.\nStart Docker Desktop and try again.",
                suggestions=[
                    "Make sure Docker Desktop is installed and running",
                    "Try manually starting containers: docker compose up -d postgres redis",
                    "Check whether port 8001 is in use by another app",
                    "Check logs/app.log and logs/error.log for details",
                ],
            )
            sys.exit(1)

        # Step 2: Check and free port if needed
        print_progress("Step 2/4", f"Checking port {PORT} availability...")
        if is_port_in_use(PORT):
            print_progress("Step 2/4", f"Port {PORT} is in use, attempting to free it...")
            if not kill_processes_on_port(PORT, max_retries=3):
                show_startup_error_messagebox(
                    "Startup Failed",
                    f"Port {PORT} is in use and could not be freed automatically.",
                    suggestions=[
                        f"Manually kill the process using port {PORT}",
                        "Close any other instances of Price Error Bot",
                        f"Run: Get-NetTCPConnection -LocalPort {PORT} | ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force }}",
                        "Restart your computer if the port is stuck",
                    ],
                )
                sys.exit(1)
            if not wait_for_port_free(PORT, timeout_seconds=10):
                show_startup_error_messagebox(
                    "Startup Failed",
                    f"Port {PORT} did not become available after killing processes.",
                    suggestions=[
                        "Wait a few seconds and try again",
                        "Check if another application is using the port",
                        f"Manually verify port {PORT} is free",
                    ],
                )
                sys.exit(1)

        # Step 3: Start the server
        print_progress("Step 3/4", "Starting server...")
        if not start_server():
            show_startup_error_messagebox(
                "Startup Failed",
                "The Price Error Bot server failed to start within the timeout period.",
                suggestions=[
                    "Check if port 8001 is still in use",
                    "Verify Docker containers are running: docker ps",
                    "Check application logs for detailed error messages",
                    "Try restarting Docker Desktop",
                    "Ensure no firewall is blocking the port",
                ],
            )
            sys.exit(1)

        # Step 4: Create and show the window (webview import only here)
        print_progress("Step 4/4", "Opening application window...")
        print("\n" + "="*60)
        print("  Application is ready!")
        print("="*60 + "\n")

        # Check WebView2 availability before attempting to use pywebview
        if not check_webview2_available():
            show_startup_error_messagebox(
                "Startup Failed",
                "Microsoft Edge WebView2 Runtime is not installed.\n\nThe application requires WebView2 to display the UI.",
                suggestions=[
                    "Download and install Microsoft Edge WebView2 Runtime",
                    "Visit: https://developer.microsoft.com/microsoft-edge/webview2/",
                    "Or install Microsoft Edge browser (includes WebView2)",
                ],
            )
            sys.exit(1)

        try:
            import webview
            # Suppress script error dialogs in WebView2 if possible
            try:
                # Some pywebview versions support settings
                if hasattr(webview, 'settings'):
                    webview.settings['ALLOW_DOWNLOADS'] = False
            except Exception:
                pass  # Settings may not be available in all versions
        except ImportError:
            show_startup_error_messagebox(
                "Startup Failed",
                "pywebview is not installed. Install with: pip install pywebview",
                suggestions=["Run: pip install pywebview"],
            )
            sys.exit(1)

        try:
            window = webview.create_window(
                title=WINDOW_TITLE,
                url=URL,
                width=WINDOW_WIDTH,
                height=WINDOW_HEIGHT,
                min_size=(MIN_WIDTH, MIN_HEIGHT),
                resizable=True,
                text_select=True,
            )
            # Wrap webview.start() with error isolation
            try:
                webview.start(func=on_closed, debug=False)
            except Exception as e:
                if logger is not None:
                    logger.error("Webview runtime error: %s", e, exc_info=True)
                show_startup_error_messagebox(
                    "Application Error",
                    f"The application window encountered an error:\n\n{str(e)}",
                    suggestions=[
                        "Check if WebView2 Runtime is installed",
                        "Try reinstalling Microsoft Edge WebView2 Runtime",
                        "Check logs/error.log for details",
                    ],
                )
                sys.exit(1)
        except ImportError as e:
            if logger is not None:
                logger.error("Webview import error: %s", e)
            show_startup_error_messagebox(
                "Startup Failed",
                "Failed to import pywebview. The UI cannot be displayed.",
                suggestions=["Reinstall pywebview: pip install pywebview"],
            )
            sys.exit(1)
        except Exception as e:
            if logger is not None:
                logger.error("Webview error: %s", e, exc_info=True)
            show_startup_error_messagebox(
                "Startup Failed",
                f"Failed to open application window:\n\n{str(e)}",
                suggestions=[
                    "Check if WebView2 runtime is installed",
                    "Try running the application as administrator",
                    "Check logs/error.log for details",
                ],
            )
            sys.exit(1)

        if logger is not None:
            logger.info("Application closed.")

    except KeyboardInterrupt:
        if logger is not None:
            logger.info("Application interrupted by user")
        sys.exit(0)
    except Exception as e:
        error_msg = f"Fatal error in main(): {e}"
        if logger is not None:
            logger.critical(error_msg, exc_info=True)
        else:
            print(f"FATAL ERROR: {error_msg}", file=sys.stderr, flush=True)
            traceback.print_exc()
        try:
            show_startup_error_messagebox(
                "Fatal Error",
                f"The application encountered a fatal error:\n\n{str(e)}\n\nCheck logs/error.log for details.",
                suggestions=[
                    "Check logs/error.log for detailed error information",
                    "Verify Docker Desktop is running",
                    "Ensure all dependencies are installed",
                    "Try running: python launcher.py (for more detailed errors)",
                ],
            )
        except Exception:
            print(f"\n{'='*60}", flush=True)
            print(f"FATAL ERROR: {error_msg}", flush=True)
            print(f"{'='*60}\n", flush=True)
            input("Press Enter to exit...")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nApplication interrupted by user.", flush=True)
        sys.exit(0)
    except Exception as e:
        # This should rarely be reached due to main()'s try-except,
        # but it's a safety net
        print(f"\nFATAL: Unhandled exception: {e}", file=sys.stderr, flush=True)
        traceback.print_exc()
        sys.exit(1)
