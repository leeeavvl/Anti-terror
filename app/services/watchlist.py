import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.generic_api import GenericApiConfig
from app.connectors.registry import CONNECTOR_TYPES
from app.connectors.telegram import TelegramConfig
from app.connectors.vk import VkConfig
from app.models import WatchSource


def list_sources(db: Session) -> list[WatchSource]:
    return list(db.scalars(select(WatchSource).order_by(WatchSource.added_at.desc())))


def get_source(db: Session, source_id: int) -> WatchSource | None:
    return db.get(WatchSource, source_id)


def add_source(
    db: Session,
    *,
    platform_label: str,
    connector_type: str,
    source_identifier: str,
    display_name: str,
    added_by: str,
    config_raw: str | None = None,
    vk_token_env_var: str | None = None,
    tg_token_env_var: str | None = None,
) -> WatchSource:
    """Единственная точка, через которую новый источник попадает в систему —
    это и есть требование «мониторится только то, что специалист явно добавил»."""

    if connector_type not in CONNECTOR_TYPES:
        raise ValueError(f"Неизвестный тип коннектора: {connector_type!r}")

    if not source_identifier.strip():
        raise ValueError("Идентификатор источника обязателен")

    # Валидация конфига здесь, а не молча в момент опроса — иначе опечатка
    # выглядит как «у источника просто нет новых постов».
    config_json = None
    if connector_type == "generic_api":
        if not config_raw or not config_raw.strip():
            raise ValueError("Для generic_api необходимо указать конфигурацию (JSON)")
        try:
            config_dict = json.loads(config_raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Конфигурация — невалидный JSON: {exc}") from exc
        GenericApiConfig.model_validate(config_dict)
        config_json = config_dict
    elif connector_type == "vk":
        if not vk_token_env_var or not vk_token_env_var.strip():
            raise ValueError("Для ВКонтакте необходимо указать имя переменной окружения с токеном")
        config_dict = {"auth_env_var": vk_token_env_var.strip()}
        VkConfig.model_validate(config_dict)
        config_json = config_dict
    elif connector_type == "telegram":
        if not tg_token_env_var or not tg_token_env_var.strip():
            raise ValueError("Для Telegram необходимо указать имя переменной окружения с токеном бота")
        config_dict = {"auth_env_var": tg_token_env_var.strip()}
        TelegramConfig.model_validate(config_dict)
        config_json = config_dict

    source = WatchSource(
        platform_label=platform_label.strip(),
        connector_type=connector_type,
        source_identifier=source_identifier.strip(),
        display_name=display_name.strip() or source_identifier.strip(),
        added_by=added_by.strip(),
        config_json=config_json,
        is_active=True,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def toggle_source(db: Session, source_id: int) -> WatchSource:
    source = db.get(WatchSource, source_id)
    if source is None:
        raise ValueError(f"Источник id={source_id} не найден")
    source.is_active = not source.is_active
    db.commit()
    db.refresh(source)
    return source


def delete_source(db: Session, source_id: int) -> None:
    """Полностью удаляет источник вместе с его постами и сигналами
    (cascade настроен в models.py). Необратимо — подтверждение запрашивается
    на уровне UI (см. watchlist.html)."""
    source = db.get(WatchSource, source_id)
    if source is None:
        raise ValueError(f"Источник id={source_id} не найден")
    db.delete(source)
    db.commit()
