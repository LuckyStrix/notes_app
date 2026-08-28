from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, diagrams, graph, groups, media, notes, projects, search, settings as settings_api

app = FastAPI(title="notes_app API")

# No auth by design (trusted Tailscale-only network); permissive CORS so the
# client can be served from a different origin during local dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(groups.router)
app.include_router(notes.router)
app.include_router(media.router)
app.include_router(diagrams.router)
app.include_router(settings_api.router)
app.include_router(chat.router)
app.include_router(graph.router)
app.include_router(search.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
