import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal
from dotenv import load_dotenv
from .store import Store

log = logging.getLogger(__name__)


class TaskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    mode: Literal["demo", "live"] = "demo"
    dataset_id: str | None = None
    metrics: dict[str, str] = Field(default_factory=dict)


class Approval(BaseModel):
    digest: str = Field(min_length=64, max_length=64)
    approve: bool


def base_app(project_dir, kind, agent_factory, prepare):
    project_dir = Path(project_dir)
    load_dotenv(project_dir / ".env", override=False)
    root = Path(os.getenv("APP_DATA_DIR", str(project_dir / "data")))
    root.mkdir(parents=True, exist_ok=True)
    store = Store(root / "state.sqlite3")
    agent = agent_factory(store, root)
    active = {}

    async def work(tid):
        try:
            await agent.run(tid)
        except asyncio.CancelledError:
            task = store.get(tid)
            if task["status"] == "running":
                store.checkpoint(
                    tid,
                    "interrupted",
                    task["state"],
                    "interrupted",
                    {"message": "任务已中断，可从已保存阶段恢复"},
                )
            raise
        except Exception as exc:
            log.exception("Task failed: %s", tid)
            task = store.get(tid)
            # Provider errors can include request headers; expose only our validation failures.
            message = (
                str(exc)[:500]
                if isinstance(exc, ValueError)
                else "执行失败，请检查本地服务日志或模型配置。"
            )
            store.checkpoint(
                tid, "failed", task["state"], "failed", {"message": message}
            )
        finally:
            active.pop(tid, None)

    def launch(tid):
        active[tid] = asyncio.create_task(work(tid))

    @asynccontextmanager
    async def lifespan(app):
        store.recover(kind)
        yield
        jobs = list(active.values())
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)

    app = FastAPI(
        title="DataCanvas" if kind == "data" else "FlowPilot", lifespan=lifespan
    )
    app.state.store = store
    app.state.root = root
    app.state.agent = agent

    def get(tid):
        try:
            task = store.get(tid)
        except KeyError:
            raise HTTPException(404, "任务不存在。")
        if task["kind"] != kind:
            raise HTTPException(404, "任务不存在。")
        return task

    @app.get("/api/health")
    async def health():
        return {
            "kind": kind,
            "live_configured": bool(os.getenv("OPENAI_API_KEY")),
            "status": "ok",
        }

    @app.get("/api/tasks")
    async def tasks():
        return store.tasks(kind)

    @app.post("/api/tasks", status_code=202)
    async def create(request: TaskRequest):
        if not request.query.strip():
            raise HTTPException(422, "请输入具体问题。")
        if request.mode == "live" and not os.getenv("OPENAI_API_KEY"):
            raise HTTPException(400, "请在本地 .env 配置模型接口。")
        if sum(1 for t in active.values() if not t.done()) >= 2:
            raise HTTPException(429, "最多同时执行两个任务。")
        state = prepare(request, store)
        tid = store.create(kind, request.query.strip(), request.mode, state)
        if not store.claim(tid, ["queued"]):
            raise HTTPException(409, "任务状态冲突。")
        launch(tid)
        return {"id": tid}

    @app.get("/api/tasks/{tid}")
    async def detail(tid: str):
        return {**get(tid), "events": store.events(tid)}

    @app.get("/api/tasks/{tid}/events")
    async def events(tid: str, request: Request, after: int = 0):
        get(tid)
        try:
            cursor = max(after, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            raise HTTPException(400, "事件游标无效。")

        async def stream():
            nonlocal cursor
            idle = 0
            while not await request.is_disconnected():
                batch = store.events(tid, cursor)
                for event in batch:
                    cursor = event["seq"]
                    yield (
                        "id: "
                        + str(cursor)
                        + "\nevent: trace\ndata: "
                        + json.dumps(event, ensure_ascii=False)
                        + "\n\n"
                    )
                if get(tid)["status"] not in {"running", "queued"} and not batch:
                    yield "event: settled\ndata: {}\n\n"
                    break
                idle += 1
                if idle % 20 == 0:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.2)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/tasks/{tid}/resume")
    async def resume(tid: str):
        get(tid)
        if not store.claim(tid, ["interrupted"]):
            raise HTTPException(409, "只有中断任务可以恢复。")
        store.event(tid, "resume", {"message": "从持久化状态继续执行"})
        launch(tid)
        return {"id": tid}

    @app.post("/api/tasks/{tid}/cancel")
    async def cancel(tid: str):
        task = get(tid)
        if task["status"] not in {
            "queued",
            "running",
            "awaiting_approval",
            "interrupted",
        }:
            raise HTTPException(409, "当前任务不能取消。")
        store.checkpoint(
            tid, "cancelled", task["state"], "cancelled", {"message": "任务已取消"}
        )
        job = active.get(tid)
        if job:
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
        return {"status": "cancelled"}

    @app.post("/api/tasks/{tid}/approve")
    async def approve(tid: str, request: Approval):
        task = get(tid)
        if kind != "browser" or task["status"] != "awaiting_approval":
            raise HTTPException(409, "任务没有待确认操作。")
        state = task["state"]
        if request.digest != state.get("digest"):
            raise HTTPException(409, "确认内容与待执行内容不一致。")
        if not store.claim(tid, ["awaiting_approval"]):
            raise HTTPException(409, "任务已被其他请求处理。")
        if not request.approve:
            store.checkpoint(
                tid, "cancelled", state, "cancelled", {"message": "用户拒绝提交"}
            )
            return {"status": "cancelled"}
        state["approved"] = True
        store.checkpoint(
            tid,
            "running",
            state,
            "approved",
            {"message": "用户已确认当前内容", "digest": request.digest},
        )
        launch(tid)
        return {"status": "running"}

    @app.get("/api/tasks/{tid}/report")
    async def report(tid: str):
        task = get(tid)
        text = task["state"].get("report")
        if not text:
            raise HTTPException(409, "报告尚未生成。")
        return Response(
            text,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{kind}-{tid[:8]}.md"'
            },
        )

    return app, store, root


def mount_frontend(app, project_dir):
    dist = Path(project_dir) / "frontend/dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
