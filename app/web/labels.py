"""Человекочитаемые русские подписи для технических кодов — чтобы специалист
без технического бэкграунда видел «средний уровень», а не «medium»."""

LEVEL_LABELS = {"low": "низкий", "medium": "средний", "high": "высокий"}
CONNECTOR_LABELS = {
    "mock": "демо-режим (без реального API)",
    "vk": "ВКонтакте — официальный API",
    "telegram": "Telegram — официальный Bot API",
    "generic_api": "официальный API платформы (другое)",
}
STATUS_LABELS = {"new": "новый", "reviewed": "проверен", "dismissed": "не риск", "escalated": "эскалирован"}


def level_label(value: str | None) -> str:
    return LEVEL_LABELS.get(value, value or "—")


def connector_label(value: str) -> str:
    return CONNECTOR_LABELS.get(value, value)


def status_label(value: str) -> str:
    return STATUS_LABELS.get(value, value)


def register_filters(templates) -> None:
    templates.env.filters["level_label"] = level_label
    templates.env.filters["connector_label"] = connector_label
    templates.env.filters["status_label"] = status_label
