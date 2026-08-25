from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import Post, WatchSource
from app.services import custom_markers as custom_markers_service
from app.services import polling as polling_service
from app.services import signals as signals_service
from app.services import watchlist as watchlist_service
from app.web.highlighting import register_filters as register_highlighting_filters
from app.web.labels import register_filters as register_label_filters

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
register_label_filters(templates)
register_highlighting_filters(templates)


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    counts = signals_service.dashboard_counts(db)
    source_breakdown = signals_service.dashboard_source_breakdown(db)
    return templates.TemplateResponse(
        request, "dashboard.html", {"counts": counts, "source_breakdown": source_breakdown}
    )


@router.get("/watchlist")
def watchlist_page(request: Request, db: Session = Depends(get_db), error: str | None = None):
    sources = watchlist_service.list_sources(db)
    return templates.TemplateResponse(request, "watchlist.html", {"sources": sources, "error": error})


@router.post("/watchlist/add")
def watchlist_add(
    platform_label: str = Form(""),
    connector_type: str = Form(...),
    source_identifier: str = Form(...),
    display_name: str = Form(""),
    added_by: str = Form(...),
    config_raw: str = Form(""),
    vk_token_env_var: str = Form(""),
    tg_token_env_var: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        watchlist_service.add_source(
            db,
            platform_label=platform_label,
            connector_type=connector_type,
            source_identifier=source_identifier,
            display_name=display_name,
            added_by=added_by,
            config_raw=config_raw,
            vk_token_env_var=vk_token_env_var,
            tg_token_env_var=tg_token_env_var,
        )
    except ValueError as exc:
        return RedirectResponse(url=f"/watchlist?error={exc}", status_code=303)
    return RedirectResponse(url="/watchlist", status_code=303)


@router.post("/watchlist/{source_id}/toggle")
def watchlist_toggle(source_id: int, db: Session = Depends(get_db)):
    try:
        watchlist_service.toggle_source(db, source_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(url="/watchlist", status_code=303)


@router.post("/watchlist/{source_id}/delete")
def watchlist_delete(source_id: int, db: Session = Depends(get_db)):
    try:
        watchlist_service.delete_source(db, source_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(url="/watchlist", status_code=303)


@router.post("/watchlist/{source_id}/poll")
def watchlist_poll(source_id: int):
    found = polling_service.poll_single_source(source_id)
    if not found:
        raise HTTPException(status_code=404, detail="Источник не найден")
    return RedirectResponse(url=f"/watchlist/{source_id}?polled=1", status_code=303)


@router.get("/watchlist/{source_id}")
def watchlist_detail(source_id: int, request: Request, db: Session = Depends(get_db), polled: str | None = None):
    source = watchlist_service.get_source(db, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Источник не найден")
    posts = list(
        db.scalars(
            select(Post)
            .where(Post.source_id == source_id)
            .options(joinedload(Post.signal))
            .order_by(Post.published_at.desc())
        )
    )
    return templates.TemplateResponse(
        request, "source_detail.html", {"source": source, "posts": posts, "polled": polled == "1"}
    )


@router.get("/guide")
def guide_page(request: Request):
    return templates.TemplateResponse(request, "guide.html", {})


@router.get("/edits")
def edits_page(
    request: Request,
    db: Session = Depends(get_db),
    error: str | None = None,
    added_matches: str | None = None,
    loaded: str | None = None,
):
    manual_markers = custom_markers_service.list_manual_markers(db)
    dictionary_groups = custom_markers_service.list_dictionary_groups(db)
    return templates.TemplateResponse(
        request,
        "edits.html",
        {
            "manual_markers": manual_markers,
            "dictionary_groups": dictionary_groups,
            "error": error,
            "added_matches": added_matches,
            "loaded": loaded,
        },
    )


@router.post("/edits/add")
def edits_add(
    phrase: str = Form(...),
    weight: float = Form(3.0),
    added_by: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        _, matches = custom_markers_service.add_marker(db, phrase=phrase, weight=weight, added_by=added_by)
    except ValueError as exc:
        return RedirectResponse(url=f"/edits?error={exc}", status_code=303)
    return RedirectResponse(url=f"/edits?added_matches={matches}", status_code=303)


@router.post("/edits/{marker_id}/delete")
def edits_delete(marker_id: int, db: Session = Depends(get_db)):
    try:
        custom_markers_service.delete_marker(db, marker_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(url="/edits", status_code=303)


@router.post("/edits/load-dictionary")
def edits_load_dictionary(added_by: str = Form(...), db: Session = Depends(get_db)):
    added, matches = custom_markers_service.load_mayak_dictionary(db, added_by=added_by)
    return RedirectResponse(url=f"/edits?loaded={added}&added_matches={matches}", status_code=303)


@router.get("/signals")
def signals_page(request: Request, db: Session = Depends(get_db)):
    open_signals = signals_service.list_open_signals(db)
    return templates.TemplateResponse(request, "signals.html", {"signals": open_signals})


@router.post("/signals/{signal_id}/review")
def signals_review(
    signal_id: int,
    status: str = Form(...),
    reviewed_by: str = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        signals_service.review_signal(db, signal_id, status=status, reviewed_by=reviewed_by, note=note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url="/signals", status_code=303)
