"""REST API for the Company Brain.

Security:
- Every endpoint except /health requires a Bearer API key (maps to an agent).
- Rate limiting via slowapi.
- CORS locked down (empty by default = same-origin only).
- Security headers on every response.
- Request body size cap.
- All access is written to the audit log (agent + action, never the key).
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
    brain = Brain()  # loads embedder + vector store
    yield


app = FastAPI(title="Company Brain", version=__version__, lifespan=lifespan)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _ratelimit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


# CORS: only origins explicitly listed in CORS_ORIGINS are allowed.
_origins = [o.strip() for o in config.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Reject oversized bodies early.
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
        # Fail closed: if no keys are configured, refuse all authed routes.
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


class SearchIn(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=50)
    category: str | None = None
    agent: str | None = None
    tag: str | None = None


# --- Routes -------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "version": __version__, "auth": auth_configured()}


@app.get("/stats")
async def stats(agent: str = Depends(require_agent)):
    return brain.stats()


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
    )
    audit("save", agent=agent, note_id=note["id"], category=note["category"])
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
        searched_by=agent,
    )
    audit("search", agent=agent, query_len=len(body.query), results=len(hits))
    return {"query": body.query, "results": hits}


@app.get("/get/{note_id}")
async def get(note_id: str, agent: str = Depends(require_agent)):
    note = brain.get(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Not found")
    audit("get", agent=agent, note_id=note_id)
    return note


@app.get("/recent")
async def recent(n: int = 20, agent: str = Depends(require_agent)):
    n = max(1, min(n, 100))
    return {"results": brain.recent(n)}


@app.get("/activity")
async def activity(who: str | None = None, n: int = 20, agent: str = Depends(require_agent)):
    n = max(1, min(n, 100))
    return {"results": brain.activity(agent=who, n=n)}


@app.post("/reindex")
async def reindex(agent: str = Depends(require_agent)):
    audit("reindex", agent=agent)
    return brain.reindex()


@app.delete("/delete/{note_id}")
async def delete(note_id: str, agent: str = Depends(require_agent)):
    ok = brain.delete(note_id)
    audit("delete", agent=agent, note_id=note_id, ok=ok)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": note_id}
