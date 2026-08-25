"""Подсветка совпавших маркеров прямо в тексте поста.

Это и есть «объяснимость» на практике: специалист должен не гадать, почему
появился сигнал, а сразу видеть в тексте поста конкретную фразу, которая
совпала с маркером риска.

Текст поста приходит из внешнего источника (демо-пул, VK, Telegram, любой
generic_api) и считается непроверенным — сначала он полностью экранируется
как HTML (через markupsafe.escape), и только потом в уже экранированную
строку вставляются теги <mark> вокруг найденных фраз. Так пост не может
содержать что-то, что выполнится в браузере специалиста."""

import re

from markupsafe import Markup, escape


def highlight_markers(text: str, matched_markers: list[dict]) -> Markup:
    escaped = str(escape(text or ""))

    keywords = sorted({m["matched_keyword"] for m in matched_markers if m.get("matched_keyword")}, key=len, reverse=True)
    if not keywords:
        return Markup(escaped)

    pattern = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)
    highlighted = pattern.sub(lambda m: f'<mark class="hit">{m.group(0)}</mark>', escaped)
    return Markup(highlighted)


def register_filters(templates) -> None:
    templates.env.filters["highlight_markers"] = highlight_markers
