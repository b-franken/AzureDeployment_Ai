import importlib.util
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

spec = importlib.util.spec_from_file_location("ws", Path("src/app/api/routes/ws.py"))
ws = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws)
ws_router = ws.router


def test_ws_route_unique_and_start_endpoint_present() -> None:
    app = FastAPI()
    app.include_router(ws_router)
    TestClient(app)
    routes = [r.path for r in app.routes]
    assert routes.count("/ws/deploy/{deployment_id}") == 1

    deploy_source = Path("src/app/api/routes/deploy.py").read_text()
    assert '@router.post("/start")' in deploy_source
