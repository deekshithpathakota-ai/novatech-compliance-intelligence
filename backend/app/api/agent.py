import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents import orchestrator
from app.agents.llm import router as model_router
from app.auth.deps import Principal, require
from app.compliance.snapshot import _aware
from app.database.session import SessionLocal, get_db
from app.models import AgentRun, AgentStep, Conversation, Message, ToolCall
from app.services.tenancy import get_owned
from app.tools.gateway import REGISTRY, ToolError

router = APIRouter(prefix="/api", tags=["agent"])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None
    intent: dict | None = None  # context-aware action buttons may pin the workflow (validated server-side)


ALLOWED_INTENT_KEYS = {"intent", "control_code", "finding_code", "framework"}


def run_json(run: AgentRun) -> dict:
    return {"id": run.id, "conversation_id": run.conversation_id, "objective": run.objective, "intent": run.intent,
            "status": run.status, "plan": run.plan, "plan_done": (run.result or {}).get("plan_done", []),
            "engine": run.engine, "model": run.model, "started_at": _aware(run.started_at).isoformat(),
            "completed_at": _aware(run.completed_at).isoformat() if run.completed_at else None,
            "duration_ms": run.duration_ms, "llm_calls": run.llm_calls, "tokens_in": run.tokens_in,
            "tokens_out": run.tokens_out, "content": (run.result or {}).get("content"),
            "cards": (run.result or {}).get("cards", []), "error": run.error}


def step_json(s: AgentStep) -> dict:
    return {"id": s.id, "seq": s.seq, "event": s.event_type, "phase": s.phase, "title": s.title, "status": s.status,
            "tool": s.tool_name, "detail": s.detail, "evidence_count": s.evidence_count, "duration_ms": s.duration_ms,
            "at": _aware(s.created_at).isoformat()}


@router.post("/agent/chat")
def chat(body: ChatIn, p: Principal = Depends(require("AGENT_USE")), db: Session = Depends(get_db)):
    forced = None
    if body.intent:
        forced = {k: v for k, v in body.intent.items() if k in ALLOWED_INTENT_KEYS and isinstance(v, str)}
        if forced.get("intent") not in orchestrator.WORKFLOWS:
            forced = None
    try:
        run = orchestrator.start_run(db, p, body.message.strip(), body.conversation_id, forced)
    except ToolError as e:
        raise HTTPException(404, {"code": e.code, "message": e.message})
    return run_json(run)


@router.post("/agent/run")
def run_agent(body: ChatIn, p: Principal = Depends(require("AGENT_USE")), db: Session = Depends(get_db)):
    return chat(body, p, db)


@router.get("/agent/runs")
def list_runs(limit: int = 20, p: Principal = Depends(require("AGENT_USE")), db: Session = Depends(get_db)):
    rows = db.execute(select(AgentRun).where(AgentRun.company_id == p.company_id, AgentRun.user_id == p.user_id)
                      .order_by(AgentRun.id.desc()).limit(min(limit, 100))).scalars().all()
    return [run_json(r) for r in rows]


@router.get("/agent/runs/{run_id}")
def get_run(run_id: int, p: Principal = Depends(require("AGENT_USE")), db: Session = Depends(get_db)):
    return run_json(get_owned(db, AgentRun, run_id, p.company_id, "Agent run"))


@router.get("/agent/runs/{run_id}/steps")
def get_steps(run_id: int, p: Principal = Depends(require("AGENT_USE")), db: Session = Depends(get_db)):
    get_owned(db, AgentRun, run_id, p.company_id, "Agent run")
    steps = db.execute(select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.seq)).scalars().all()
    tools = db.execute(select(ToolCall).where(ToolCall.run_id == run_id).order_by(ToolCall.id)).scalars().all()
    return {"steps": [step_json(s) for s in steps],
            "tool_calls": [{"tool": t.tool_name, "status": t.status, "authorized": t.authorized, "risk": t.risk_level,
                            "duration_ms": t.duration_ms, "attempts": t.attempts, "summary": t.result_summary} for t in tools]}


@router.get("/agent/runs/{run_id}/stream")
async def stream(run_id: int, request: Request, p: Principal = Depends(require("AGENT_USE"))):
    """Server-Sent Events: agent.started, plan.created, retrieval.*, finding.detected, approval.required,
    action.executed, verification.*, memory.updated, agent.completed."""
    with SessionLocal() as db:
        get_owned(db, AgentRun, run_id, p.company_id, "Agent run")

    async def gen():
        seen: dict[int, str] = {}
        idle = 0
        while True:
            if await request.is_disconnected():
                break
            with SessionLocal() as db:
                run = db.get(AgentRun, run_id)
                steps = db.execute(select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.seq)).scalars().all()
                for s in steps:
                    sig = f"{s.status}|{s.title}"
                    if seen.get(s.id) != sig:
                        seen[s.id] = sig
                        yield f"event: step\ndata: {json.dumps(step_json(s))}\n\n"
                done = run.status in ("COMPLETED", "FAILED", "AWAITING_APPROVAL") and run.completed_at is not None
                if done and any(s.event_type in ("agent.completed", "agent.failed") for s in steps):
                    yield f"event: run\ndata: {json.dumps(run_json(run), default=str)}\n\n"
                    break
            idle += 1
            if idle % 50 == 0:  # SSE comment every ~15 s keeps proxies (Render, Vercel, corporate) from closing the stream
                yield ": keep-alive\n\n"
            if idle > 600:  # ~3 minutes safety cap
                yield "event: timeout\ndata: {}\n\n"
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/conversations")
def conversations(p: Principal = Depends(require("AGENT_USE")), db: Session = Depends(get_db)):
    rows = db.execute(select(Conversation, func.count(Message.id)).join(Message, Message.conversation_id == Conversation.id, isouter=True)
                      .where(Conversation.company_id == p.company_id, Conversation.user_id == p.user_id)
                      .group_by(Conversation.id).order_by(Conversation.updated_at.desc()).limit(40)).all()
    return [{"id": c.id, "title": c.title, "updated_at": _aware(c.updated_at).isoformat(), "messages": n} for c, n in rows]


@router.get("/conversations/{conv_id}/messages")
def messages(conv_id: int, p: Principal = Depends(require("AGENT_USE")), db: Session = Depends(get_db)):
    c = get_owned(db, Conversation, conv_id, p.company_id, "Conversation")
    if c.user_id != p.user_id:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Conversation not found."})
    rows = db.execute(select(Message).where(Message.conversation_id == conv_id).order_by(Message.id)).scalars().all()
    return [{"id": m.id, "role": m.role, "content": m.content, "cards": m.cards, "run_id": m.run_id,
             "at": _aware(m.created_at).isoformat()} for m in rows]


@router.get("/agent/tools")
def tools(p: Principal = Depends(require("AGENT_USE"))):
    return {"tools": [s.public() | {"you_can_use": p.has(s.required_permission)} for s in REGISTRY.values()],
            "model_routing": model_router.describe()}
