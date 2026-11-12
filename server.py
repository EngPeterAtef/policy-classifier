"""The API behind the page, and the server for the built page itself.

    GET  /api/config     which model is configured
    GET  /api/cases      the labeled cases, to load into the form
    GET  /api/policy     policy.md, split into what the classifier is shown and what it is not
    POST /api/classify   classify one event
    GET  /api/results    the last eval run (results.json), or null

The API key stays on the server. The page never sees it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import classifier
from evaluate import RESULTS_JSON, load_cases

WEB_DIST = Path(__file__).resolve().parent / "web" / "dist"

app = FastAPI(title="Policy alignment classifier")


class Event(BaseModel):
    kind: str
    payload: dict[str, Any]
    context: Optional[dict[str, Any]] = None


@app.get("/api/config")
def config() -> dict[str, Any]:
    chosen = classifier.settings()
    return {"configured": chosen["configured"], "provider": chosen["provider"], "model": chosen["model"]}


@app.get("/api/cases")
def cases() -> list[dict[str, Any]]:
    return load_cases()


@app.get("/api/policy")
def policy() -> dict[str, str]:
    shown, hidden = classifier.read_policy()
    return {"shown": shown, "hidden": hidden}


@app.post("/api/classify")
def classify(event: Event) -> dict[str, Any]:
    if event.kind not in classifier.KINDS:
        raise HTTPException(status_code=422, detail=f"kind must be one of {', '.join(classifier.KINDS)}")
    return classifier.classify(event.kind, event.payload, event.context)


@app.get("/api/results")
def results() -> Optional[dict[str, Any]]:
    if not RESULTS_JSON.exists():
        return None
    return json.loads(RESULTS_JSON.read_text(encoding="utf-8"))


# The built page. Registered last so that the /api routes win.
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def page(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="no such API route")
        return FileResponse(WEB_DIST / "index.html")
