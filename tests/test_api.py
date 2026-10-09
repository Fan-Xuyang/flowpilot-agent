import sys
import time
from pathlib import Path
from fastapi.testclient import TestClient
from shared.api import base_app

ROOT = Path(__file__).resolve().parents[1]


class PausingAgent:
    def __init__(self, store, root):
        self.store = store

    async def run(self, tid):
        task = self.store.get(tid)
        state = task["state"]
        if state.get("approved"):
            self.store.checkpoint(
                tid, "completed", state, "completed", {"message": "done"}
            )
        else:
            state["digest"] = "a" * 64
            self.store.checkpoint(
                tid,
                "awaiting_approval",
                state,
                "approval_required",
                {"message": "approve"},
            )


def wait(client, tid, status):
    for _ in range(100):
        task = client.get("/api/tasks/" + tid).json()
        if task["status"] == status:
            return task
        time.sleep(0.01)
    raise AssertionError(task)


def test_approval_binding_replay_and_rejection(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app, store, _ = base_app(tmp_path, "browser", PausingAgent, lambda req, store: {})
    with TestClient(app) as client:
        tid = client.post("/api/tasks", json={"query": "test"}).json()["id"]
        wait(client, tid, "awaiting_approval")
        bad = client.post(
            "/api/tasks/" + tid + "/approve", json={"digest": "b" * 64, "approve": True}
        )
        assert bad.status_code == 409
        assert (
            client.post(
                "/api/tasks/" + tid + "/approve",
                json={"digest": "a" * 64, "approve": True},
            ).status_code
            == 200
        )
        done = wait(client, tid, "completed")
        assert (
            client.post(
                "/api/tasks/" + tid + "/approve",
                json={"digest": "a" * 64, "approve": True},
            ).status_code
            == 409
        )
        cursor = done["events"][-2]["seq"]
        response = client.get(
            "/api/tasks/" + tid + "/events", headers={"Last-Event-ID": str(cursor)}
        )
        assert response.status_code == 200 and "event: settled" in response.text
        assert f"id: {cursor}\n" not in response.text
        tid2 = client.post("/api/tasks", json={"query": "reject"}).json()["id"]
        wait(client, tid2, "awaiting_approval")
        assert (
            client.post(
                "/api/tasks/" + tid2 + "/approve",
                json={"digest": "a" * 64, "approve": False},
            ).status_code
            == 200
        )
        assert store.get(tid2)["status"] == "cancelled"
        assert client.post("/api/tasks", json={"query": "  "}).status_code == 422
        assert (
            client.post(
                "/api/tasks", json={"query": "test", "mode": "live"}
            ).status_code
            == 400
        )


def test_portal_only_accepts_confirmed_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "portal"))
    # Load the real portal routes without starting a browser.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "portal_app",
        ROOT / "app/__init__.py",
        submodule_search_locations=[str(ROOT / "app")],
    )
    pkg = importlib.util.module_from_spec(spec)
    sys.modules["portal_app"] = pkg
    spec.loader.exec_module(pkg)
    module = importlib.import_module("portal_app.main")
    from portal_app.agent import demo_plan, digest

    payload = demo_plan("信息技术部采购 2 台电脑，预算 12000，用于开发测试").payload.model_dump()
    store = module.store
    tid = store.create(
        "browser", "test", "demo", {"digest": digest(payload), "approved": False}
    )
    with TestClient(module.app) as client:
        assert (
            client.post("/portal/submit", json={"task_id": tid, **payload}).status_code
            == 403
        )
        state = store.get(tid)["state"]
        state["approved"] = True
        store.checkpoint(tid, "running", state, "approved", {})
        assert (
            client.post(
                "/portal/submit", json={"task_id": tid, **payload, "quantity": 3}
            ).status_code
            == 403
        )
        first = client.post("/portal/submit", json={"task_id": tid, **payload})
        second = client.post("/portal/submit", json={"task_id": tid, **payload})
        assert first.status_code == 200 and second.json() == first.json()
        with store.connect() as c:
            assert c.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 1
