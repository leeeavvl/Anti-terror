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
    # Пост содержит фото/видео/стикер и т.п. Автоматический анализ картинок
    # (символика вроде свастики) в системе не производится — это требует
    # компьютерного зрения, которого здесь нет, и наивное распознавание по
    # форме путает нацистскую символику с религиозной (индуизм/буддизм).
    # Вместо этого такой пост явно помечается «нужен ручной просмотр», а не
    # молча пропускается, как было раньше при пустом тексте.
    has_media: Mapped[bool] = mapped_column(default=False)

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
    score: Mapped[float] = mapped_column()
    level: Mapped[str] = mapped_column()
    matched_markers: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(default="new")
    reviewed_by: Mapped[str | None] = mapped_column(nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    review_note: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    post: Mapped["Post"] = relationship(back_populates="signal")


class CustomMarker(Base):
    """Слово-маркер, добавленное специалистом — вручную через вкладку «Правки»
    либо массово из загруженного словаря (см. risk_engine/mayak_dictionary.json).

    Работает по тому же принципу, что и встроенные маркеры в risk_engine/rules.py
    — просто хранится в БД, а не в коде, чтобы специалист мог добавлять их сам,
    без участия разработчика. Никакой отдельной модели ИИ здесь нет: добавленное
    слово подключается к тому же объяснимому движку скоринга (см.
    risk_engine/scorer.py), поэтому найденные по нему сигналы так же показывают,
    какая фраза сработала.

    category — ключ группировки для скоринга (см. scorer.py: не больше одного
    засчитанного совпадения на категорию). Для ручных записей из «Правок» это
    сама фраза (каждая — своя независимая категория); для записей из словаря —
    настоящая категория маркера (recruitment, secrecy, planning и т.д.), чтобы
    несколько слов одной категории в одном посте не раздували балл суммированием."""

    __tablename__ = "custom_markers"

    id: Mapped[int] = mapped_column(primary_key=True)
    phrase: Mapped[str] = mapped_column()
    category: Mapped[str] = mapped_column(default="Добавлено специалистом")
    category_title: Mapped[str] = mapped_column(default="")
    weight: Mapped[float] = mapped_column(default=3)
    source: Mapped[str] = mapped_column(default="")
    note: Mapped[str] = mapped_column(default="")
    added_by: Mapped[str] = mapped_column(default="")
    added_at: Mapped[datetime] = mapped_column(default=_utcnow)
