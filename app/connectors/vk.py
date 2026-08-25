"""Готовый коннектор для ВКонтакте — официальный API, метод wall.get.

Специалисту не нужно писать JSON-конфиг: у watchlist-источника с
connector_type="vk" в config_json хранится только имя переменной окружения
с токеном (auth_env_var); сам паблик/аккаунт берётся из уже существующего
поля source_identifier (ссылка вида https://vk.com/название или просто
короткое имя). Коннектор всегда читает только публичную стену через
официальный метод wall.get с filter=owner (посты самого паблика/аккаунта,
а не гостевые записи) — не читает личные сообщения и не пишет ничего на
платформу.
"""

import logging
import os
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import requests
from pydantic import BaseModel

from app.config import GENERIC_API_TIMEOUT_SECONDS
from app.connectors.base import RawPost

if TYPE_CHECKING:
    from app.models import WatchSource

logger = logging.getLogger("risk_watchlist.connectors.vk")

VK_API_URL = "https://api.vk.com/method/wall.get"
DEFAULT_API_VERSION = "5.199"
POSTS_PER_POLL = 20


class VkConfig(BaseModel):
    auth_env_var: str
    api_version: str = DEFAULT_API_VERSION


def _extract_domain(source_identifier: str) -> str:
    value = source_identifier.strip()
    # vk.com и vk.ru — оба официальных домена ВКонтакте, ссылки бывают на любой из них
    value = re.sub(r"^(https?://)?(www\.)?vk\.(com|ru)/", "", value, flags=re.IGNORECASE)
    return value.strip("/ ")


class VkConnector:
    def fetch_new_posts(self, source: "WatchSource", since: datetime | None) -> list[RawPost]:
        try:
            config = VkConfig.model_validate(source.config_json or {})
        except Exception as exc:
            logger.error(
                "Источник %s (id=%s): некорректный config_json для VK: %s",
                source.display_name, source.id, exc,
            )
            return []

        token = os.environ.get(config.auth_env_var)
        if not token:
            logger.error(
                "Источник %s (id=%s): переменная окружения %s не задана — опрос VK пропущен "
                "для этого источника, остальные продолжают опрашиваться.",
                source.display_name, source.id, config.auth_env_var,
            )
            return []

        domain = _extract_domain(source.source_identifier)
        if not domain:
            logger.error(
                "Источник %s (id=%s): не удалось определить короткое имя паблика/аккаунта из %r",
                source.display_name, source.id, source.source_identifier,
            )
            return []

        params = {
            "domain": domain,
            "count": POSTS_PER_POLL,
            "filter": "owner",
            "access_token": token,
            "v": config.api_version,
        }

        try:
            response = requests.get(VK_API_URL, params=params, timeout=GENERIC_API_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.RequestException as exc:
            logger.error("Источник %s (id=%s): ошибка запроса к VK API: %s", source.display_name, source.id, exc)
            return []
        except ValueError as exc:
            logger.error(
                "Источник %s (id=%s): ответ VK API не является валидным JSON: %s",
                source.display_name, source.id, exc,
            )
            return []

        if "error" in payload:
            err = payload["error"]
            logger.error(
                "Источник %s (id=%s): VK API вернул ошибку %s: %s",
                source.display_name, source.id, err.get("error_code"), err.get("error_msg"),
            )
            return []

        items = payload.get("response", {}).get("items", [])

        effective_since = since or datetime.fromtimestamp(0, tz=timezone.utc)
        if effective_since.tzinfo is None:
            effective_since = effective_since.replace(tzinfo=timezone.utc)

        posts: list[RawPost] = []
        for item in items:
            post_date = datetime.fromtimestamp(item.get("date", 0), tz=timezone.utc)
            if post_date <= effective_since:
                continue

            text = (item.get("text") or "").strip()
            has_media = bool(item.get("attachments"))
            if not text and not has_media:
                continue

            if not text:
                # Картинку/видео/стикер система не анализирует (нет
                # компьютерного зрения) — помечаем пост для ручного
                # просмотра специалистом, а не пропускаем молча.
                text = "[медиа без подписи — фото/видео/стикер, требуется ручной просмотр]"

            from_id = item.get("from_id")
            posts.append(
                RawPost(
                    external_id=str(item.get("id")),
                    text=text,
                    author_label=f"id{from_id}" if from_id is not None else "",
                    published_at=post_date,
                    has_media=has_media,
                )
            )

        return posts
