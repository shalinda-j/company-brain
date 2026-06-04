"""REST API for the Company Brain v2.

Security: every endpoint except /health requires a Bearer API key (mapped to an
agent). Rate limiting, locked-down CORS, security headers, body-size cap, and an
audit log that never records secrets.

Projects: pass a project via the `project` field/query (default: configured
default project).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from brain import __version__
from brain.config import config
from brain.core import Brain
from brain.security import audit, auth_configured, verify_key

limiter = Limiter(key_func=get_remote_address, default_limits=[config.rate_limit])
brain: Brain | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global brain
    brain = Brain()
    yield


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
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No API keys configured. Set BRAIN_API_KEYS.",
        )
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    agent = verify_key(token)
    if not agent:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return agent


# --- Schemas ------------------------------------------------------------
class SaveIn(BaseModel):
    content: str = Field(min_length=1)
    title: str | None = None
    category: str = "notes"
    tags: list[str] = Field(default_factory=list)
    source: str = ""
    links: list[str] = Field(default_factory=list)
    project: str | None = None
    allow_duplicate: bool = False


class SearchIn(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=50)
    category: str | None = None
    agent: str | None = None
    tag: str | None = None
    project: str | None = None


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
        project=body.project,
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
        searched_by=agent,
    )
    audit("search", agent=agent, project=body.project, results=len(hits))
    return {"query": body.query, "results": hits}


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


@app.get("/recent")
async def recent(n: int = 20, project: str | None = None, agent: str = Depends(require_agent)):
    n = max(1, min(n, 100))
    return {"results": brain.recent(n, project=project)}


@app.get("/activity")
async def activity(
    who: str | None = None,
    n: int = 20,
    project: str | None = None,
    agent: str = Depends(require_agent),
):
    n = max(1, min(n, 100))
    return {"results": brain.activity(agent=who, n=n, project=project)}


@app.post("/maintenance/consolidate")
async def consolidate(project: str | None = None, agent: str = Depends(require_agent)):
    res = brain.consolidate(project=project)
    audit("consolidate", agent=agent, project=res["project"], removed=res["removed"])
    return res


@app.post("/reindex")
async def reindex(project: str | None = None, agent: str = Depends(require_agent)):
    audit("reindex", agent=agent, project=project)
    return brain.reindex(project=project)


@app.delete("/delete/{note_id}")
async def delete(note_id: str, project: str | None = None, agent: str = Depends(require_agent)):
    ok = brain.delete(note_id, project=project)
    audit("delete", agent=agent, note_id=note_id, ok=ok)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": note_id}
