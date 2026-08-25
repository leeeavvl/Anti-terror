import logging
from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy import select

from app.connectors.registry import get_connector
from app.db import SessionLocal
from app.models import Post, RiskSignal, WatchSource
from app.risk_engine.scorer import score_post
from app.services.custom_markers import as_extra_markers

logger = logging.getLogger("risk_watchlist.polling")


def poll_all_sources() -> None:
    """Опрашивает только активные источники из watchlist — единственный способ
    для приложения узнать о новом контенте. Каждый источник обрабатывается в
    своей сессии/транзакции, чтобы сбой одного источника (сеть, неверный
    конфиг) не мешал опросу остальных."""

    db = SessionLocal()
    try:
        source_ids = list(db.scalars(select(WatchSource.id).where(WatchSource.is_active.is_(True))))
    finally:
        db.close()

    for source_id in source_ids:
        poll_single_source(source_id)


def poll_single_source(source_id: int) -> bool:
    """Опрашивает ровно один источник немедленно, вне обычного расписания —
    для кнопки «Проверить сейчас», когда специалист только что что-то поменял
    (токен, состав администраторов бота и т.п.) и не хочет ждать следующий
    автоматический цикл. Работает независимо от is_active — источник для
    ручной проверки не обязан быть включён в фоновый опрос.

    Возвращает True, если источник найден и опрошен (независимо от того,
    нашлись новые посты или нет), False — если источника с таким id нет."""

    db = SessionLocal()
    try:
        source = db.get(WatchSource, source_id)
        if source is None:
            return False
        _poll_one_source(db, source)
        db.commit()
        return True
    except Exception:
        db.rollback()
        logger.exception("Ошибка при опросе источника id=%s", source_id)
        return True
    finally:
        db.close()


def _poll_one_source(db, source: WatchSource) -> None:
    connector = get_connector(source.connector_type)
    raw_posts = connector.fetch_new_posts(source, source.last_polled_at)
    extra_markers = as_extra_markers(db)

    for raw in raw_posts:
        exists = db.execute(
            select(Post.id).where(Post.source_id == source.id, Post.external_id == raw.external_id)
        ).first()
        if exists:
            continue

        post = Post(
            source_id=source.id,
            external_id=raw.external_id,
            text=raw.text,
            author_label=raw.author_label,
            published_at=raw.published_at,
            has_media=raw.has_media,
        )
        db.add(post)
        db.flush()

        assessment = score_post(raw.text, extra_markers=extra_markers)
        if assessment.level is not None:
            db.add(
                RiskSignal(
                    post_id=post.id,
                    score=assessment.score,
                    level=assessment.level,
                    matched_markers=[asdict(m) for m in assessment.matched_markers],
                )
            )

    source.last_polled_at = datetime.now(timezone.utc)
    db.add(source)
