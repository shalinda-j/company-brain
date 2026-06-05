"""REST API for the Company Brain v3 (multi-layer memory).

Security: every endpoint except /health requires a Bearer API key (mapped to an
agent). Rate limiting, locked-down CORS, security headers, body-size cap, and an
audit log that never records secrets.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from brain import __version__
from brain.config import config
from brain.core import Brain
from brain.scheduler import heartbeat_loop
from brain.security import audit, auth_configured, verify_key

limiter = Limiter(key_func=get_remote_address, default_limits=[config.rate_limit])
brain: Brain | None = None
_stop: asyncio.Event | None = None
_hb_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global brain, _stop, _hb_task
    brain = Brain()
    _stop = asyncio.Event()
    if config.heartbeat_interval > 0:
        _hb_task = asyncio.create_task(heartbeat_loop(brain, _stop))
    yield
    if _stop:
        _stop.set()
    if _hb_task:
        try:
            await _hb_task
        except Exception:
            pass


app = FastAPI(title="Company Brain", version=__version__, lifespan=lifespan)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _ratelimit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


_origins = [o.strip() for o in config.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Project", "X-Agent"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > config.max_body_bytes:
        return JSONResponse(status_code=413, content={"detail": "Body too large"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


async def require_agent(authorization: str | None = Header(default=None)) -> str:
    if not auth_configured():
        raise HTTPException(status_code=503, detail="No API keys configured. Set BRAIN_API_KEYS.")
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    agent = verify_key(token)
    if not agent:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return agent


# --- Schemas ------------------------------------------------------------
class SaveIn(BaseModel):
    content: str = Field(min_length=1)
    title: str | None = None
    category: str = "notes"
    tags: list[str] = Field(default_factory=list)
    source: str = ""
    links: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    project: str | None = None
    pinned: bool = False
    allow_duplicate: bool = False


class SearchIn(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=50)
    category: str | None = None
    agent: str | None = None
    tag: str | None = None
    project: str | None = None
    user: str | None = None
    include_archived: bool = False
    hybrid: bool | None = None


class RecallIn(BaseModel):
    query: str = Field(min_length=1)
    token_budget: int | None = Field(default=None, ge=200, le=8000)
    project: str | None = None
    user: str | None = None


class IngestIn(BaseModel):
    text: str = Field(min_length=1)
    title: str | None = None
    source: str = "conversation"
    tags: list[str] = Field(default_factory=list)
    project: str | None = None


class FeedbackIn(BaseModel):
    note_id: str
    useful: bool = True
    project: str | None = None


class SoulIn(BaseModel):
    text: str = Field(min_length=1)
    project: str | None = None
    agent_scope: bool = False


class PrincipleIn(BaseModel):
    principle: str = Field(min_length=1)
    project: str | None = None
    agent_scope: bool = False


class PrefIn(BaseModel):
    key: str = Field(min_length=1)
    value: str
    project: str | None = None
    agent_scope: bool = False


class OntologyIn(BaseModel):
    tag: str = Field(min_length=1)
    parent: str = Field(min_length=1)


class FactIn(BaseModel):
    subject: str = Field(min_length=1)
    value: str = Field(min_length=1)
    predicate: str = "is"
    project: str | None = None


class BlockIn(BaseModel):
    name: str = Field(min_length=1)
    text: str = Field(min_length=1)
    project: str | None = None
    agent_scope: bool = False


class PinIn(BaseModel):
    note_id: str
    pinned: bool = True
    project: str | None = None


class DirectiveIn(BaseModel):
    text: str = Field(min_length=1)
    project: str | None = None


class CheckpointIn(BaseModel):
    note: str = Field(min_length=1)
    session: str = "default"
    files: list[str] = Field(default_factory=list)
    git_ref: str = ""
    next: str = ""
    status: str = "working"
    project: str | None = None


class AliasIn(BaseModel):
    alias: str = Field(min_length=1)
    canonical: str = Field(min_length=1)


class ArchiveIn(BaseModel):
    note_id: str
    archived: bool = True
    project: str | None = None


class ImportIn(BaseModel):
    bundle: dict
    project: str | None = None


# --- Routes -------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "version": __version__, "auth": auth_configured()}


@app.get("/projects")
async def projects(agent: str = Depends(require_agent)):
    return {"projects": brain.projects()}


@app.get("/stats")
async def stats(project: str | None = None, agent: str = Depends(require_agent)):
    return brain.stats(project=project)


@app.post("/save")
@limiter.limit(config.rate_limit)
async def save(request: Request, body: SaveIn, agent: str = Depends(require_agent)):
    note = brain.save(
        content=body.content,
        title=body.title,
        category=body.category,
        tags=body.tags,
        source=body.source,
        agent=agent,
        links=body.links,
        entities=body.entities,
        project=body.project,
        pinned=body.pinned,
        allow_duplicate=body.allow_duplicate,
    )
    audit(
        "save",
        agent=agent,
        note_id=note["id"],
        project=note["project"],
        duplicate=note.get("duplicate"),
    )
    return note


@app.post("/ingest")
@limiter.limit(config.rate_limit)
async def ingest(request: Request, body: IngestIn, agent: str = Depends(require_agent)):
    note = brain.ingest(
        text=body.text,
        title=body.title,
        source=body.source,
        tags=body.tags,
        agent=agent,
        project=body.project,
    )
    audit("ingest", agent=agent, note_id=note["id"], project=note["project"])
    return note


@app.post("/search")
@limiter.limit(config.rate_limit)
async def search(request: Request, body: SearchIn, agent: str = Depends(require_agent)):
    hits = brain.search(
        query=body.query,
        limit=body.limit,
        category=body.category,
        agent=body.agent,
        tag=body.tag,
        project=body.project,
        user=body.user,
        include_archived=body.include_archived,
        hybrid_search=body.hybrid,
        searched_by=agent,
    )
    audit("search", agent=agent, project=body.project, results=len(hits))
    return {"query": body.query, "results": hits}


@app.post("/recall")
@limiter.limit(config.rate_limit)
async def recall(request: Request, body: RecallIn, agent: str = Depends(require_agent)):
    bundle = brain.recall(
        query=body.query,
        project=body.project,
        user=body.user,
        agent=agent,
        token_budget=body.token_budget,
        searched_by=agent,
    )
    audit("recall", agent=agent, project=body.project, tokens=bundle["approx_tokens"])
    return bundle


@app.post("/feedback")
async def feedback(body: FeedbackIn, agent: str = Depends(require_agent)):
    res = brain.feedback(note_id=body.note_id, useful=body.useful, project=body.project)
    if res is None:
        raise HTTPException(status_code=404, detail="Not found")
    audit("feedback", agent=agent, note_id=body.note_id, useful=body.useful)
    return res


@app.get("/get/{note_id}")
async def get(note_id: str, project: str | None = None, agent: str = Depends(require_agent)):
    note = brain.get(note_id, project=project)
    if not note:
        raise HTTPException(status_code=404, detail="Not found")
    audit("get", agent=agent, note_id=note_id)
    return note


@app.get("/related/{note_id}")
async def related(
    note_id: str, project: str | None = None, limit: int = 8, agent: str = Depends(require_agent)
):
    return {"related": brain.related(note_id, project=project, limit=max(1, min(limit, 50)))}


@app.get("/recent")
async def recent(n: int = 20, project: str | None = None, agent: str = Depends(require_agent)):
    return {"results": brain.recent(max(1, min(n, 100)), project=project)}


@app.get("/activity")
async def activity(
    who: str | None = None,
    n: int = 20,
    project: str | None = None,
    agent: str = Depends(require_agent),
):
    return {"results": brain.activity(agent=who, n=max(1, min(n, 100)), project=project)}


# --- graph --------------------------------------------------------------
@app.get("/entities")
async def entities(project: str | None = None, agent: str = Depends(require_agent)):
    return {"entities": brain.entities(project=project)}


@app.get("/entities/{entity}/neighbors")
async def entity_neighbors(
    entity: str, project: str | None = None, agent: str = Depends(require_agent)
):
    return {"entity": entity, "neighbors": brain.entity_neighbors(entity, project=project)}


@app.get("/entities/{entity}/notes")
async def entity_notes(
    entity: str, project: str | None = None, agent: str = Depends(require_agent)
):
    return {"entity": entity, "notes": brain.entity_notes(entity, project=project)}


# --- self / preferences / ontology -------------------------------------
@app.get("/soul")
async def get_soul(project: str | None = None, agent: str = Depends(require_agent)):
    return {"soul": brain.get_soul(project=project)}


@app.post("/soul")
async def set_soul(body: SoulIn, agent: str = Depends(require_agent)):
    scoped = agent if body.agent_scope else None
    audit("set_soul", agent=agent, project=body.project, scoped=body.agent_scope)
    return {"soul": brain.set_soul(body.text, project=body.project, agent=scoped)}


@app.post("/soul/learn")
async def learn_principle(body: PrincipleIn, agent: str = Depends(require_agent)):
    scoped = agent if body.agent_scope else None
    audit("learn_principle", agent=agent, project=body.project, scoped=body.agent_scope)
    return {"soul": brain.learn_principle(body.principle, project=body.project, agent=scoped)}


@app.get("/preferences")
async def get_prefs(project: str | None = None, agent: str = Depends(require_agent)):
    return {"preferences": brain.get_preferences(project=project)}


@app.post("/preferences")
async def set_pref(body: PrefIn, agent: str = Depends(require_agent)):
    scoped = agent if body.agent_scope else None
    audit("set_pref", agent=agent, project=body.project, scoped=body.agent_scope)
    return {
        "preferences": brain.set_preference(
            body.key, body.value, project=body.project, agent=scoped
        )
    }


@app.get("/ontology")
async def get_ontology(agent: str = Depends(require_agent)):
    return {"taxonomy": brain.get_ontology()}


@app.post("/ontology")
async def set_ontology(body: OntologyIn, agent: str = Depends(require_agent)):
    audit("set_ontology", agent=agent)
    return {"taxonomy": brain.set_ontology(body.tag, body.parent)}


# --- maintenance --------------------------------------------------------
@app.post("/maintenance/consolidate")
async def consolidate(project: str | None = None, agent: str = Depends(require_agent)):
    res = brain.consolidate(project=project)
    audit("consolidate", agent=agent, project=res["project"], removed=res["removed"])
    return res


@app.post("/maintenance/dream")
async def dream(project: str | None = None, agent: str = Depends(require_agent)):
    res = brain.dream(project=project)
    audit("dream", agent=agent, project=res["project"], digests=res["digests_created"])
    return res


@app.post("/maintenance/tick")
async def tick(project: str | None = None, agent: str = Depends(require_agent)):
    res = brain.tick(project=project)
    audit("tick", agent=agent, project=res["project"])
    return res


@app.post("/reindex")
async def reindex(project: str | None = None, agent: str = Depends(require_agent)):
    audit("reindex", agent=agent, project=project)
    return brain.reindex(project=project)


# --- facts (bi-temporal) ------------------------------------------------
@app.post("/facts")
async def add_fact(body: FactIn, agent: str = Depends(require_agent)):
    fact = brain.add_fact(
        subject=body.subject,
        value=body.value,
        predicate=body.predicate,
        agent=agent,
        project=body.project,
    )
    audit("add_fact", agent=agent, project=body.project, subject=body.subject)
    return fact


@app.get("/facts")
async def get_facts(
    subject: str | None = None, project: str | None = None, agent: str = Depends(require_agent)
):
    return {"facts": brain.facts(subject=subject, project=project)}


@app.get("/facts/{subject}/history")
async def fact_history(
    subject: str, project: str | None = None, agent: str = Depends(require_agent)
):
    return {"subject": subject, "history": brain.fact_history(subject, project=project)}


# --- core memory blocks -------------------------------------------------
@app.get("/blocks")
async def get_blocks(project: str | None = None, agent: str = Depends(require_agent)):
    return {"blocks": brain.list_blocks(project=project)}


@app.post("/blocks")
async def set_block(body: BlockIn, agent: str = Depends(require_agent)):
    scoped = agent if body.agent_scope else None
    audit("set_block", agent=agent, project=body.project, name=body.name, scoped=body.agent_scope)
    return {"block": brain.set_block(body.name, body.text, project=body.project, agent=scoped)}


@app.get("/block/{name}")
async def get_block(name: str, project: str | None = None, agent: str = Depends(require_agent)):
    return {"name": name, "block": brain.get_block(name, project=project)}


# --- graph: communities + multi-hop + aliases ---------------------------
@app.get("/communities")
async def communities(project: str | None = None, agent: str = Depends(require_agent)):
    return {"communities": brain.communities(project=project)}


@app.get("/graph")
async def graph_data(
    project: str | None = None,
    mode: str = "entities",
    limit: int = 400,
    agent: str = Depends(require_agent),
):
    if mode not in ("entities", "notes"):
        raise HTTPException(status_code=422, detail="mode must be 'entities' or 'notes'")
    return brain.graph_data(project=project, mode=mode, limit=max(1, min(limit, 2000)))


@app.get("/entities/{entity}/multihop")
async def entity_multihop(
    entity: str, depth: int = 2, project: str | None = None, agent: str = Depends(require_agent)
):
    return {
        "entity": entity,
        "depth": depth,
        "reachable": brain.entity_multihop(entity, depth=depth, project=project),
    }


@app.post("/alias")
async def set_alias(body: AliasIn, agent: str = Depends(require_agent)):
    audit("set_alias", agent=agent)
    return {"aliases": brain.set_alias(body.alias, body.canonical)}


# --- directives (always-applied) ----------------------------------------
@app.get("/directives")
async def get_directives(project: str | None = None, agent: str = Depends(require_agent)):
    return {"directives": brain.directives(project=project)}


@app.post("/directives")
async def add_directive(body: DirectiveIn, agent: str = Depends(require_agent)):
    note = brain.add_directive(body.text, project=body.project, agent=agent)
    audit("add_directive", agent=agent, project=note["project"], note_id=note["id"])
    return note


@app.post("/pin")
async def pin(body: PinIn, agent: str = Depends(require_agent)):
    res = brain.set_pinned(body.note_id, body.pinned, project=body.project)
    if res is None:
        raise HTTPException(status_code=404, detail="Not found")
    audit("pin", agent=agent, note_id=body.note_id, pinned=body.pinned)
    return res


# --- archival -----------------------------------------------------------
@app.post("/archive")
async def archive(body: ArchiveIn, agent: str = Depends(require_agent)):
    res = brain.set_archived(body.note_id, body.archived, project=body.project)
    if res is None:
        raise HTTPException(status_code=404, detail="Not found")
    audit("archive", agent=agent, note_id=body.note_id, archived=body.archived)
    return res


# --- doctor / metrics / export / import ---------------------------------
@app.get("/doctor")
async def doctor(project: str | None = None, agent: str = Depends(require_agent)):
    return brain.doctor(project=project)


@app.get("/metrics")
async def metrics(agent: str = Depends(require_agent)):
    return {"metrics": brain.metrics()}


@app.get("/export")
async def export(project: str | None = None, agent: str = Depends(require_agent)):
    audit("export", agent=agent, project=project)
    return brain.export(project=project)


@app.post("/import")
async def import_bundle(body: ImportIn, agent: str = Depends(require_agent)):
    res = brain.import_bundle(body.bundle, project=body.project)
    audit("import", agent=agent, project=res["project"], notes=res["imported_notes"])
    return res


@app.post("/maintenance/sleep")
async def sleep_cycle(project: str | None = None, agent: str = Depends(require_agent)):
    res = brain.sleep_cycle(project=project)
    audit("sleep", agent=agent, project=res["project"])
    return res


# --- real-time session / checkpoint layer -------------------------------
@app.post("/checkpoint")
@limiter.limit(config.rate_limit)
async def checkpoint(request: Request, body: CheckpointIn, agent: str = Depends(require_agent)):
    rec = brain.checkpoint(
        note=body.note,
        session_id=body.session,
        agent=agent,
        files=body.files,
        git_ref=body.git_ref,
        next_step=body.next,
        status=body.status,
        project=body.project,
    )
    audit("checkpoint", agent=agent, project=body.project, session=rec["session"])
    return rec


@app.get("/resume")
async def resume(
    session: str | None = None,
    project: str | None = None,
    n: int = 5,
    agent: str = Depends(require_agent),
):
    return brain.resume(session_id=session, project=project, n=max(1, min(n, 50)))


@app.get("/sessions")
async def sessions(project: str | None = None, agent: str = Depends(require_agent)):
    return {"sessions": brain.sessions(project=project)}


@app.delete("/delete/{note_id}")
async def delete(note_id: str, project: str | None = None, agent: str = Depends(require_agent)):
    ok = brain.delete(note_id, project=project)
    audit("delete", agent=agent, note_id=note_id, ok=ok)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": note_id}
