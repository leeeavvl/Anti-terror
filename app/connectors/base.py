from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.models import WatchSource


@dataclass(frozen=True)
class RawPost:
    """Один публичный пост/комментарий, полученный от платформы."""

    external_id: str
    text: str
    author_label: str
    published_at: datetime


class PlatformConnector(Protocol):
    """Интерфейс подключения к одной конкретной платформе.

    Ровно один метод — структурная гарантия того, что коннектор не может
    ни прочитать личные сообщения, ни выполнить какое-либо действие на
    платформе (бан/жалоба/отправка сообщения). Коннектор отвечает только
    за получение новых постов из ОДНОГО источника (source), не за поиск
    источников — источники в систему попадают только через явное
    добавление в watchlist специалистом.
    """

    def fetch_new_posts(self, source: "WatchSource", since: datetime | None) -> list[RawPost]:
        ...
