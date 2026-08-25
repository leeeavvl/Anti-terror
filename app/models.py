from datetime import datetime, timezone

from sqlalchemy import JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WatchSource(Base):
    """Публичный источник (паблик/канал/аккаунт), явно добавленный специалистом.

    Единственная точка входа новых данных в систему — poll_all_sources()
    опрашивает только строки этой таблицы, никакого автопоиска источников нет.
    """

    __tablename__ = "watch_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform_label: Mapped[str] = mapped_column(default="")
    connector_type: Mapped[str] = mapped_column()
    source_identifier: Mapped[str] = mapped_column()
    display_name: Mapped[str] = mapped_column(default="")
    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    added_by: Mapped[str] = mapped_column(default="")
    added_at: Mapped[datetime] = mapped_column(default=_utcnow)
    is_active: Mapped[bool] = mapped_column(default=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(nullable=True)

    posts: Mapped[list["Post"]] = relationship(back_populates="source", cascade="all, delete-orphan")


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_post_source_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("watch_sources.id"))
    external_id: Mapped[str] = mapped_column()
    text: Mapped[str] = mapped_column()
    author_label: Mapped[str] = mapped_column(default="")
    published_at: Mapped[datetime] = mapped_column()
    fetched_at: Mapped[datetime] = mapped_column(default=_utcnow)

    source: Mapped["WatchSource"] = relationship(back_populates="posts")
    signal: Mapped["RiskSignal | None"] = relationship(back_populates="post", uselist=False, cascade="all, delete-orphan")


class RiskSignal(Base):
    """Объяснимый сигнал риска для одного поста — только для просмотра специалистом.

    Ревью (status/reviewed_by/review_note) меняет исключительно эту таблицу и
    никогда не обращается к внешним API платформ.
    """

    __tablename__ = "risk_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"))
    score: Mapped[int] = mapped_column()
    level: Mapped[str] = mapped_column()
    matched_markers: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(default="new")
    reviewed_by: Mapped[str | None] = mapped_column(nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    review_note: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    post: Mapped["Post"] = relationship(back_populates="signal")
