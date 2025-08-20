import asyncio
import logging
import os
import signal
import socket
import sys
import time
from pathlib import Path


def _detect_repo_root() -> Path:
    here = Path(__file__).resolve().parent
    for cand in (here, here.parent):
        if (cand / "src" / "app" / "api" / "main.py").exists():
            return cand
    return here


REPO_ROOT = _detect_repo_root()
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class PlatformLauncher:
    def __init__(self):
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.running = False
        self.shutting_down = False

    def setup_minimal_environment(self):
        os.environ.setdefault("ENVIRONMENT", "development")
        os.environ.setdefault("DEBUG", "false")
        os.environ.setdefault("LLM_PROVIDER", "ollama")
        os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
        os.environ.setdefault("OLLAMA_MODEL", "llama3.1")
        if not os.getenv("JWT_SECRET_KEY"):
            from cryptography.fernet import Fernet

            os.environ["JWT_SECRET_KEY"] = Fernet.generate_key().decode()
        os.environ.setdefault("MAX_MEMORY", "25")
        os.environ.setdefault("MAX_TOTAL_MEMORY", "100")
        for p in [
            Path.home() / ".devops_ai",
            Path.home() / ".devops_ai" / "memory",
            Path.home() / ".devops_ai" / "audit",
            REPO_ROOT / "data",
            REPO_ROOT / "logs",
        ]:
            p.mkdir(parents=True, exist_ok=True)

    async def check_ollama(self) -> bool:
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                r = await client.get("http://localhost:11434/api/tags")
            if r.status_code == 200 and r.json().get("models"):
                logger.info("✓ Ollama is running with %d models", len(r.json().get("models", [])))
                return True
            logger.warning("⚠️  Ollama is running but has no models")
            logger.info("  Run: ollama pull llama3.1")
            return False
        except Exception:
            logger.warning("⚠️  Ollama is not running")
            logger.info("  Install: https://ollama.ai  then run: ollama serve")
            return False

    async def start_api_server(self) -> bool:
        logger.info("Starting API server...")
        host = os.getenv("API_HOST", "127.0.0.1")
        port = int(os.getenv("API_PORT", "8000"))
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if s.connect_ex((host, port)) == 0:
                logger.warning("Port %s is already in use", port)
                return False
        finally:
            s.close()

        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join([str(SRC_PATH), env.get("PYTHONPATH", "")])

        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "uvicorn",
                "app.api.main:app",
                "--host",
                host,
                "--port",
                str(port),
                cwd=str(REPO_ROOT),
                stdout=None,
                stderr=None,
                env=env,
            )
            self.processes["api"] = process

            import httpx

            deadline = time.time() + 40
            async with httpx.AsyncClient() as client:
                url = f"http://{host}:{port}/api/health"
                while time.time() < deadline:
                    if process.returncode is not None:
                        logger.error("API server process exited early")
                        return False
                    try:
                        r = await client.get(url, timeout=1.5)
                        if r.status_code == 200:
                            logger.info("✓ API server started successfully")
                            logger.info("  API docs: http://%s:%s/docs", host, port)
                            return True
                    except Exception:
                        await asyncio.sleep(1)
            logger.error("API server failed to become healthy within timeout")
            return False
        except Exception as e:
            logger.error("Failed to start API server: %s", e)
            return False

    async def start_mcp_server(self) -> bool:
        logger.info("Starting MCP server...")
        env = os.environ.copy()
        env["MCP_TRANSPORT"] = env.get("MCP_TRANSPORT", "stdio")
        env["PYTHONPATH"] = os.pathsep.join([str(SRC_PATH), env.get("PYTHONPATH", "")])
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "app.mcp.server",
                cwd=str(REPO_ROOT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            self.processes["mcp"] = process
            logger.info("✓ MCP server started")
            return True
        except Exception as e:
            logger.warning("MCP server could not start (optional): %s", e)
            return False

    async def test_basic_functionality(self) -> bool:
        logger.info("Testing basic functionality...")
        try:
            from app.ai.agents import AgentFactory
            from app.ai.agents.chain import ChainLink
            from app.ai.agents.types import AgentContext

            factory = AgentFactory()
            context = AgentContext(user_id="test_user", environment="dev", dry_run=True)
            agent = factory.create("chain", context=context)

            async def test_processor(data):
                return {"status": "success", "data": data}

            agent.add_link(ChainLink(name="test", processor=test_processor))
            result = await agent.run("test")
            if result.success:
                logger.info("✓ Basic agent functionality working")
                return True
            logger.error("Agent test failed: %s", result.error)
            return False
        except Exception as e:
            logger.error("Functionality test failed: %s", e)
            return False

    async def run(self) -> bool:
        self.running = True
        print("\n" + "=" * 60)
        print("DevOps AI Platform - Starting Up")
        print("=" * 60 + "\n")

        logger.info("Setting up environment...")
        self.setup_minimal_environment()

        if not await self.check_ollama():
            logger.warning("Running without Ollama - some features may be limited")

        await self.test_basic_functionality()

        api_ok = await self.start_api_server()
        if not api_ok:
            logger.error("Failed to start API server - exiting")
            return False

        await self.start_mcp_server()

        print("\n" + "=" * 60)
        print("Platform is running!")
        print("=" * 60)
        print("\n Access points:")
        print("  - API: http://127.0.0.1:8000")
        print("  - Docs: http://127.0.0.1:8000/docs")
        print("  - Health: http://127.0.0.1:8000/api/health")
        print("\n Quick test commands:")
        print("  curl http://127.0.0.1:8000/api/health")
        print("  curl -X POST http://127.0.0.1:8000/api/chat \\")
        print("    -H 'Content-Type: application/json' \\")
        print('    -d \'{"input": "Hello"}\'')
        print("\nPress Ctrl+C to stop all services\n")

        try:
            while self.running:
                await asyncio.sleep(1)
                for name, process in list(self.processes.items()):
                    if process.returncode is not None:
                        logger.warning("Process %s has stopped", name)
                        del self.processes[name]
        except KeyboardInterrupt:
            logger.info("Shutdown requested...")
        return True

    async def shutdown(self):
        if self.shutting_down:
            return
        self.shutting_down = True
        self.running = False
        logger.info("Shutting down services...")
        for name, process in list(self.processes.items()):
            try:
                if process.returncode is None:
                    logger.info("Stopping %s...", name)
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=5.0)
                    except TimeoutError:
                        logger.warning("Force killing %s", name)
                        process.kill()
                else:
                    logger.info("%s already exited", name)
            except ProcessLookupError:
                logger.info("%s already gone", name)
            except Exception as e:
                logger.warning("Error stopping %s: %s", name, e)
        self.processes.clear()
        logger.info("All services stopped")


async def main() -> bool:
    launcher = PlatformLauncher()

    def _sig_handler(sig, frame):
        logger.info("Signal received, initiating shutdown...")
        asyncio.create_task(launcher.shutdown())

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    try:
        success = await launcher.run()
        await launcher.shutdown()
        return success
    except Exception as e:
        logger.exception("Fatal error: %s", e)
        await launcher.shutdown()
        return False


if __name__ == "__main__":
    try:
        ok = asyncio.run(main())
        sys.exit(0 if ok else 1)
    except KeyboardInterrupt:
        print("\nShutdown complete")
        sys.exit(0)
    except Exception as e:
        logger.exception("Fatal error: %s", e)
        sys.exit(1)
