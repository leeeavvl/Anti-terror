"""Референсный коннектор для «официального API платформы».

Универсальный REST-клиент с конфигурируемым маппингом полей — не привязан
к конкретной соцсети. Под конкретную платформу подставляется конфигурация
конкретной watchlist-записи (connector_type="generic_api" + config_json).
Если реального токена нет — коннектор логирует понятную ошибку и возвращает
пустой список, не роняя процесс: остальные источники в watchlist продолжают
опрашиваться независимо от этого.
"""

import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import requests
from pydantic import BaseModel, field_validator

from app.config import GENERIC_API_TIMEOUT_SECONDS
from app.connectors.base import RawPost

if TYPE_CHECKING:
    from app.models import WatchSource

logger = logging.getLogger("risk_watchlist.connectors.generic_api")


class FieldMap(BaseModel):
    external_id: str
    text: str
    author_label: str
    published_at: str


class GenericApiConfig(BaseModel):
    """Валидируется при добавлении источника в watchlist (см. services/watchlist.py),
    чтобы опечатка в конфиге не выглядела как «у источника просто нет новых постов»."""

    base_url: str
    endpoint: str
    items_path: str | None = None
    field_map: FieldMap
    auth_type: str = "bearer_header"
    auth_param_name: str = "Authorization"
    auth_env_var: str
    since_param: str | None = None
    since_format: str = "iso8601"

    @field_validator("auth_type")
    @classmethod
    def _validate_auth_type(cls, v: str) -> str:
        if v not in ("bearer_header", "query_param"):
            raise ValueError("auth_type должен быть 'bearer_header' или 'query_param'")
        return v

    @field_validator("since_format")
    @classmethod
    def _validate_since_format(cls, v: str) -> str:
        if v not in ("iso8601", "unix"):
            raise ValueError("since_format должен быть 'iso8601' или 'unix'")
        return v


def _get_dotted(data: Any, path: str) -> Any:
    value = data
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit():
            idx = int(part)
            value = value[idx] if 0 <= idx < len(value) else None
        else:
            return None
        if value is None:
            return None
    return value


def _parse_published_at(raw: Any) -> datetime:
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


class GenericApiConnector:
    """Всегда выполняет только GET-запрос — метод не читается из конфига.

    Это осознанное ограничение: через настройку конфига нельзя превратить
    универсальный REST-клиент ни в поисковый инструмент (никаких query-параметров
    поиска — только фиксированный source_identifier одного источника), ни в
    инструмент, совершающий действия на платформе.
    """

    def fetch_new_posts(self, source: "WatchSource", since: datetime | None) -> list[RawPost]:
        try:
            config = GenericApiConfig.model_validate(source.config_json or {})
        except Exception as exc:
            logger.error(
                "Источник %s (id=%s): некорректный config_json для generic_api: %s",
                source.display_name, source.id, exc,
            )
            return []

        token = os.environ.get(config.auth_env_var)
        if not token:
            logger.error(
                "Источник %s (id=%s): переменная окружения %s не задана — "
                "опрос generic_api пропущен для этого источника, остальные продолжают опрашиваться.",
                source.display_name, source.id, config.auth_env_var,
            )
            return []

        url = config.base_url.rstrip("/") + "/" + config.endpoint.lstrip("/").format(id=source.source_identifier)

        params: dict[str, str] = {}
        headers: dict[str, str] = {}
        if config.auth_type == "bearer_header":
            headers[config.auth_param_name] = f"Bearer {token}"
        else:
            params[config.auth_param_name] = token

        if config.since_param and since is not None:
            if config.since_format == "unix":
                params[config.since_param] = str(int(since.timestamp()))
            else:
                params[config.since_param] = since.isoformat()

        try:
            response = requests.get(url, params=params, headers=headers, timeout=GENERIC_API_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.RequestException as exc:
            logger.error("Источник %s (id=%s): ошибка запроса к %s: %s", source.display_name, source.id, url, exc)
            return []
        except ValueError as exc:
            logger.error(
                "Источник %s (id=%s): ответ %s не является валидным JSON: %s",
                source.display_name, source.id, url, exc,
            )
            return []

        items = _get_dotted(payload, config.items_path) if config.items_path else payload
        if not isinstance(items, list):
            logger.error(
                "Источник %s (id=%s): по items_path=%r не найден список постов в ответе.",
                source.display_name, source.id, config.items_path,
            )
            return []

        posts: list[RawPost] = []
        for item in items:
            external_id = _get_dotted(item, config.field_map.external_id)
            text = _get_dotted(item, config.field_map.text)
            author_label = _get_dotted(item, config.field_map.author_label) or ""
            published_raw = _get_dotted(item, config.field_map.published_at)
            if external_id is None or text is None:
                continue
            posts.append(
                RawPost(
                    external_id=str(external_id),
                    text=str(text),
                    author_label=str(author_label),
                    published_at=_parse_published_at(published_raw),
                )
            )

        return posts
