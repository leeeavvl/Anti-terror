"""Коннектор для отдельной публичной веб-страницы по прямой ссылке.

Не привязан к конкретной платформе и не использует какой-либо официальный
API — потому что у большинства простых сайтов (блоги, новостные страницы)
такого API просто нет. Вместо этого коннектор скачивает HTML страницы
обычным HTTP GET (так же, как это делает браузер при обычном просмотре
публичной страницы — без авторизации, без обхода чего-либо) и извлекает
видимый текст.

ВАЖНОЕ ОГРАНИЧЕНИЕ: это работает только для страниц, которые отдают текст
статьи прямо в HTML (обычные серверно-рендерящиеся сайты). Сайты, которые
требуют для чтения контента браузерную сессию/авторизацию/JavaScript
(например dzen.ru — там даже на публичную статью Яндекс отвечает
редиректом на форму единого входа sso.passport.yandex.ru ещё до отдачи
какого-либо содержимого — проверено вручную), этим способом прочитать
нельзя. Обходить такую защиту (эмулировать браузер с реальной авторизацией)
этот коннектор сознательно не пытается — это вышло бы за рамки «чтения
публичной страницы» и потребовало бы реальных учётных данных пользователя
платформы, которые здесь никогда не обрабатываются.

У одиночной страницы нет понятия «список новых постов», как у ленты
канала — поэтому коннектор следит за страницей целиком: если извлечённый
текст отличается от того, что был при прошлом опросе, это считается новым
контентом для проверки. Хэш последнего известного текста хранится в
config_json источника — это единственное состояние, которое ведёт этот
коннектор, и оно не выходит за пределы локальной базы приложения.
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import requests
from bs4 import BeautifulSoup

from app.config import GENERIC_API_TIMEOUT_SECONDS
from app.connectors.base import RawPost

if TYPE_CHECKING:
    from app.models import WatchSource

logger = logging.getLogger("risk_watchlist.connectors.webpage")

USER_AGENT = "Mozilla/5.0 (compatible; RiskWatchlistBot/1.0; +monitoring one explicit public page)"
MAX_TEXT_LENGTH = 20000


def _extract_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    lines = [line.strip() for line in soup.get_text(separator="\n").splitlines()]
    return "\n".join(line for line in lines if line)


class WebpageConnector:
    def fetch_new_posts(self, source: "WatchSource", since: datetime | None) -> list[RawPost]:
        url = source.source_identifier.strip()
        if not url.startswith(("http://", "https://")):
            logger.error(
                "Источник %s (id=%s): идентификатор должен быть полной ссылкой (http:// или https://): %r",
                source.display_name, source.id, url,
            )
            return []

        try:
            response = requests.get(
                url, headers={"User-Agent": USER_AGENT}, timeout=GENERIC_API_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            logger.error(
                "Источник %s (id=%s): ошибка запроса к %s: %s", source.display_name, source.id, url, exc,
            )
            return []

        text = _extract_visible_text(response.text)[:MAX_TEXT_LENGTH]
        if not text:
            logger.warning(
                "Источник %s (id=%s): не удалось извлечь текст со страницы %s — возможно, сайту нужен "
                "JavaScript или авторизация для показа контента (простой HTTP-запрос этого не умеет).",
                source.display_name, source.id, url,
            )
            return []

        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

        previous_hash = (source.config_json or {}).get("last_content_hash")
        if previous_hash == content_hash:
            return []  # текст страницы не менялся с прошлого опроса

        source.config_json = {**(source.config_json or {}), "last_content_hash": content_hash}

        return [
            RawPost(
                external_id=content_hash,
                text=text,
                author_label=url,
                published_at=datetime.now(timezone.utc),
            )
        ]
