import json
import secrets
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from shared.api import base_app, mount_frontend
from .agent import BrowserAgent, Procurement, digest

PROJECT = Path(__file__).resolve().parents[1]
app, store, root = base_app(PROJECT, "browser", BrowserAgent, lambda request, store: {})


@app.get("/portal", response_class=HTMLResponse)
async def portal():
    return (PROJECT / "app/portal.html").read_text(encoding="utf-8")


class Submission(Procurement):
    task_id: str


@app.post("/portal/submit")
async def submit(request: Submission):
    try:
        task = store.get(request.task_id)
    except KeyError:
        raise HTTPException(404, "任务不存在。")
    payload = request.model_dump(exclude={"task_id"})
    state = task["state"]
    if (
        task["kind"] != "browser"
        or not state.get("approved")
        or task["status"] not in {"running", "interrupted", "completed"}
        or digest(payload) != state.get("digest")
    ):
        raise HTTPException(403, "提交必须匹配已确认的任务内容。")
    with store.connect() as c:
        existing = c.execute(
            "SELECT * FROM receipts WHERE task_id=?", (request.task_id,)
        ).fetchone()
        if existing:
            return {
                "task_id": request.task_id,
                "receipt": existing["receipt"],
                "payload": json.loads(existing["payload"]),
            }
        receipt = "LOCAL-" + secrets.token_hex(5).upper()
        c.execute(
            "INSERT INTO receipts VALUES(?,?,?)",
            (request.task_id, json.dumps(payload, ensure_ascii=False), receipt),
        )
    return {"task_id": request.task_id, "receipt": receipt, "payload": payload}


@app.get("/api/tasks/{tid}/screenshot")
async def screenshot(tid: str):
    try:
        task = store.get(tid)
    except KeyError:
        raise HTTPException(404, "任务不存在。")
    name = task["state"].get("screenshot")
    if not name or not (root / name).exists():
        raise HTTPException(404, "截图尚未生成。")
    return FileResponse(root / name, media_type="image/png")


mount_frontend(app, PROJECT)
