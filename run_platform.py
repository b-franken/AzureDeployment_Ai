#!/usr/bin/env python3
"""
DevOps AI Platform - Complete Startup Script
This script starts all components of the platform with proper error handling
"""

import asyncio
import os
import sys
import signal
import logging
from pathlib import Path
from typing import Optional
import subprocess
import time


sys.path.insert(0, str(Path(__file__).parent / "src"))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PlatformLauncher:
    def __init__(self):
        self.processes = {}
        self.running = False

    def setup_minimal_environment(self):
        """Set minimal required environment variables"""

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

        dirs = [
            Path.home() / ".devops_ai",
            Path.home() / ".devops_ai" / "memory",
            Path.home() / ".devops_ai" / "audit",
            Path.cwd() / "data",
            Path.cwd() / "logs",
        ]
        for dir_path in dirs:
            dir_path.mkdir(parents=True, exist_ok=True)

    async def check_ollama(self) -> bool:
        """Check if Ollama is running"""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get("http://localhost:11434/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    models = data.get("models", [])
                    if models:
                        logger.info(
                            f"✓ Ollama is running with {len(models)} models")
                        return True
                    else:
                        logger.warning(
                            "⚠️  Ollama is running but has no models")
                        logger.info("  Run: ollama pull llama3.1")
                        return False
        except Exception:
            logger.warning("⚠️  Ollama is not running")
            logger.info("  Install from: https://ollama.ai")
            logger.info("  Then run: ollama serve")
            return False

    async def start_api_server(self):
        """Start the FastAPI server"""
        logger.info("Starting API server...")

        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('localhost', 8000))
        sock.close()

        if result == 0:
            logger.warning("Port 8000 is already in use")
            return False

        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "app.api",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            self.processes['api'] = process

            await asyncio.sleep(3)

            import httpx
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.get("http://localhost:8000/api/health")
                    if response.status_code == 200:
                        logger.info("✓ API server started successfully")
                        logger.info("  API docs: http://localhost:8000/docs")
                        return True
                except Exception:
                    pass

            logger.error("API server failed to start properly")
            return False

        except Exception as e:
            logger.error(f"Failed to start API server: {e}")
            return False

    async def start_mcp_server(self):
        """Start the MCP server (optional)"""
        logger.info("Starting MCP server (optional)...")

        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "app.mcp.server",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "MCP_TRANSPORT": "stdio"}
            )
            self.processes['mcp'] = process
            logger.info("✓ MCP server started")
            return True
        except Exception as e:
            logger.warning(f"MCP server could not start (optional): {e}")
            return False

    async def test_basic_functionality(self):
        """Test basic agent functionality"""
        logger.info("Testing basic functionality...")

        try:
            from app.ai.agents import AgentFactory
            from app.ai.agents.types import AgentContext

            factory = AgentFactory()
            context = AgentContext(
                user_id="test_user",
                environment="dev",
                dry_run=True
            )

            agent = factory.create("chain", context=context)

            from app.ai.agents.chain import ChainLink

            async def test_processor(data):
                return {"status": "success", "data": data}

            agent.add_link(ChainLink(
                name="test",
                processor=test_processor
            ))

            result = await agent.run("test")

            if result.success:
                logger.info("✓ Basic agent functionality working")
                return True
            else:
                logger.error(f"Agent test failed: {result.error}")
                return False

        except Exception as e:
            logger.error(f"Functionality test failed: {e}")
            return False

    async def run(self):
        """Main run method"""
        self.running = True

        print("\n" + "="*60)
        print("DevOps AI Platform - Starting Up")
        print("="*60 + "\n")

        logger.info("Setting up environment...")
        self.setup_minimal_environment()

        ollama_ok = await self.check_ollama()
        if not ollama_ok:
            logger.warning(
                "Running without Ollama - some features may be limited")

        await self.test_basic_functionality()

        api_ok = await self.start_api_server()
        if not api_ok:
            logger.error("Failed to start API server - exiting")
            return False

        await self.start_mcp_server()

        print("\n" + "="*60)
        print("Platform is running!")
        print("="*60)
        print("\n📍 Access points:")
        print("  - API: http://localhost:8000")
        print("  - Docs: http://localhost:8000/docs")
        print("  - Health: http://localhost:8000/api/health")
        print("\n📝 Quick test commands:")
        print("  curl http://localhost:8000/api/health")
        print("  curl -X POST http://localhost:8000/api/chat \\")
        print("    -H 'Content-Type: application/json' \\")
        print("    -d '{\"input\": \"Hello\"}'")
        print("\nPress Ctrl+C to stop all services\n")

        try:
            while self.running:
                await asyncio.sleep(1)

                for name, process in list(self.processes.items()):
                    if process.returncode is not None:
                        logger.warning(f"Process {name} has stopped")
                        del self.processes[name]

        except KeyboardInterrupt:
            logger.info("Shutdown requested...")

        return True

    async def shutdown(self):
        """Shutdown all processes"""
        self.running = False
        logger.info("Shutting down services...")

        for name, process in self.processes.items():
            logger.info(f"Stopping {name}...")
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(f"Force killing {name}")
                process.kill()

        logger.info("All services stopped")


async def main():
    """Main entry point"""
    launcher = PlatformLauncher()

    def signal_handler(sig, frame):
        logger.info("Signal received, initiating shutdown...")
        asyncio.create_task(launcher.shutdown())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        success = await launcher.run()
        await launcher.shutdown()
        return success
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        await launcher.shutdown()
        return False


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nShutdown complete")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)
