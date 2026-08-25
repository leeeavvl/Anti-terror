from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Post, RiskSignal, WatchSource

STATUSES = ("new", "reviewed", "dismissed", "escalated")


def list_open_signals(db: Session) -> list[RiskSignal]:
    stmt = (
        select(RiskSignal)
        .where(RiskSignal.status == "new")
        .join(Post)
        .options(joinedload(RiskSignal.post).joinedload(Post.source))
        .order_by(RiskSignal.score.desc(), RiskSignal.created_at.desc())
    )
    return list(db.scalars(stmt))


def review_signal(db: Session, signal_id: int, *, status: str, reviewed_by: str, note: str) -> RiskSignal:
    """Меняет только локальный статус сигнала — никогда не обращается к
    внешним API платформ и не выполняет никаких действий на них."""

    if status not in STATUSES:
        raise ValueError(f"Недопустимый статус: {status!r}")

    signal = db.get(RiskSignal, signal_id)
    if signal is None:
        raise ValueError(f"Сигнал id={signal_id} не найден")

    signal.status = status
    signal.reviewed_by = reviewed_by.strip()
    signal.reviewed_at = datetime.now(timezone.utc)
    signal.review_note = note.strip()
    db.commit()
    db.refresh(signal)
    return signal


def dashboard_counts(db: Session) -> dict:
    active_sources = db.execute(select(WatchSource).where(WatchSource.is_active.is_(True))).scalars().all()
    open_signals = db.execute(select(RiskSignal).where(RiskSignal.status == "new")).scalars().all()
    by_level = {"low": 0, "medium": 0, "high": 0}
    for s in open_signals:
        by_level[s.level] = by_level.get(s.level, 0) + 1

    # Посты с медиа (фото/видео/стикер) без подписи — их содержимое система
    # не анализирует (нет компьютерного зрения), поэтому им нужен ручной
    # просмотр специалистом; считаем только те, у которых при этом нет и
    # текстового сигнала.
    media_pending = db.execute(
        select(Post).outerjoin(RiskSignal).where(Post.has_media.is_(True), RiskSignal.id.is_(None))
    ).scalars().all()

    return {
        "active_sources": len(active_sources),
        "open_signals_total": len(open_signals),
        "by_level": by_level,
        "media_pending": len(media_pending),
    }


def dashboard_source_breakdown(db: Session) -> list[dict]:
    """Разбивка открытых сигналов по источникам — чтобы на дашборде было видно
    не только общее число сигналов, а конкретно в каком паблике/канале какой
    уровень риска обнаружен."""

    active_sources = db.execute(select(WatchSource).where(WatchSource.is_active.is_(True))).scalars().all()
    breakdown = {s.id: {"source": s, "low": 0, "medium": 0, "high": 0, "total": 0} for s in active_sources}

    stmt = (
        select(RiskSignal)
        .where(RiskSignal.status == "new")
        .join(Post)
        .options(joinedload(RiskSignal.post).joinedload(Post.source))
    )
    for signal in db.scalars(stmt):
        row = breakdown.get(signal.post.source_id)
        if row is None:
            continue  # источник мог быть приостановлен уже после появления сигнала
        row[signal.level] += 1
        row["total"] += 1

    rows = list(breakdown.values())
    rows.sort(key=lambda r: (-r["high"], -r["medium"], -r["low"], r["source"].display_name.lower()))
    return rows
