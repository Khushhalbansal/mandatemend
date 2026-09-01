from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from mandatemend.console import service

_HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_HERE / "templates"))
templates.env.filters["rupees"] = lambda p: f"{(p or 0) / 100:,.0f}"
templates.env.filters["pct"] = lambda x: f"{(x or 0) * 100:.1f}%"


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    service.build()  # run one batch and cache it before serving
    yield


app = FastAPI(title="MandateMend operator console", lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
def overview(request: Request):
    v = service.view()
    return templates.TemplateResponse(request, "overview.html", {"v": v, "sc": v.scorecard})


@app.get("/mandates", response_class=HTMLResponse)
def mandates(request: Request, cause: str = "", outcome: str = ""):
    v = service.view()
    rows = v.rows
    if cause:
        rows = [r for r in rows if r.true_cause == cause]
    if outcome == "recovered":
        rows = [r for r in rows if r.resolution.recovered]
    elif outcome == "escalated":
        rows = [r for r in rows if r.resolution.escalated_to_human]
    elif outcome == "violation":
        rows = [r for r in rows if r.violations]
    causes = sorted({r.true_cause for r in v.rows})
    return templates.TemplateResponse(
        request,
        "mandates.html",
        {"rows": rows, "causes": causes, "cause": cause, "outcome": outcome},
    )


@app.get("/mandate/{mandate_id}", response_class=HTMLResponse)
def mandate(request: Request, mandate_id: str):
    r = service.view().by_id(mandate_id)
    if r is None:
        raise HTTPException(404, "no such mandate")
    from mandatemend.audit import ledger

    return templates.TemplateResponse(
        request, "mandate.html", {"r": r, "audit": ledger.entries_for(mandate_id)}
    )


@app.get("/evidence/{mandate_id}.json")
def evidence(mandate_id: str):
    pack = service.evidence_pack(mandate_id)
    if pack is None:
        raise HTTPException(404, "no such mandate")
    return JSONResponse(
        pack,
        headers={"Content-Disposition": f'attachment; filename="evidence_{mandate_id}.json"'},
    )


@app.post("/rebuild")
def rebuild():
    service.build()
    return {"ok": True}
