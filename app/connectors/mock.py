"""Демо-коннектор.

Не обращается ни к какой реальной платформе — держит фиксированный пул из
~15 заготовленных синтетических постов и «выдаёт» их по 0-2 за вызов, по мере
того как проходит время с момента добавления источника в watchlist. Нужен,
чтобы демонстрация работала стабильно без доступа к интернету/реальному API.

Тексты в пуле — это условные, вымышленные примеры разного уровня риска для
иллюстрации механизма скоринга (app/risk_engine), а не реальная риторика
какой-либо идеологии или группы.
"""

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from app.config import MOCK_RELEASE_INTERVAL_SECONDS
from app.connectors.base import RawPost

if TYPE_CHECKING:
    from app.models import WatchSource

POOL: list[dict[str, str]] = [
    {"text": "Сегодня были классные покатушки на велике, погода супер!", "author_label": "user_214"},
    {"text": "Кто-нибудь может посоветовать книгу по программированию на Python?", "author_label": "dev_anna"},
    {"text": "Готовим ужин всей семьёй, будет плов.", "author_label": "kitchen_mike"},
    {"text": "Новый эпизод любимого сериала вышел, кто уже посмотрел?", "author_label": "series_fan"},
    {"text": "Ищу репетитора по математике для подготовки к экзамену.", "author_label": "student_2025"},
    {"text": "Сходили сегодня на концерт, было очень круто!", "author_label": "music_lena"},
    {"text": "Никто меня не понимает, чувствую себя одиноко весь день.", "author_label": "anon_77"},
    {"text": "Иногда кажется, что я никому не нужен.", "author_label": "anon_91"},
    {"text": "Они все наши враги, только мы видим правду, остальные заблуждаются.", "author_label": "user_508"},
    {
        "text": "Никто меня не понимает, весь мир против меня. Они все наши враги, только мы видим правду.",
        "author_label": "anon_133",
    },
    {
        "text": "Ищу единомышленников для серьёзного дела, пишите мне в личку, если готовы действовать.",
        "author_label": "user_902",
    },
    {
        "text": "Они все наши враги. Ищу единомышленников для серьёзного дела — напиши в личку.",
        "author_label": "user_317",
    },
    {"text": "Пора действовать жёстко, я готов на крайние меры ради идеи.", "author_label": "user_654"},
    {"text": "Они у меня получат, я устрою им, пусть готовятся.", "author_label": "user_745"},
    {
        "text": "Они все наши враги и они получат своё. Я устрою им, пора действовать жёстко, я готов на крайние меры.",
        "author_label": "user_999",
    },
]


class MockConnector:
    def fetch_new_posts(self, source: "WatchSource", since: datetime | None) -> list[RawPost]:
        added_at = source.added_at
        if added_at.tzinfo is None:
            added_at = added_at.replace(tzinfo=timezone.utc)
        effective_since = since or added_at
        if effective_since.tzinfo is None:
            effective_since = effective_since.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)

        candidates: list[RawPost] = []
        for i, item in enumerate(POOL):
            available_at = added_at + timedelta(seconds=i * MOCK_RELEASE_INTERVAL_SECONDS)
            if effective_since < available_at <= now:
                candidates.append(
                    RawPost(
                        external_id=f"mock-{source.id}-{i}",
                        text=item["text"],
                        author_label=item["author_label"],
                        published_at=available_at,
                    )
                )

        candidates.sort(key=lambda p: p.published_at)
        return candidates[:2]
