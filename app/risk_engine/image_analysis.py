"""Анализ содержимого фото через Claude (Anthropic API) — единственное место в
проекте, где решение подсказывает модель, а не прозрачное правило по словам.
Чтобы не терять объяснимость всей системы, модель не выносит скрытую оценку
"опасно/не опасно": она обязана выбрать одну из фиксированных категорий и
дать короткое текстовое описание, которое дальше подставляется в текст поста
как обычная фраза (см. connectors/telegram.py) — и уже эта фраза ловится
такими же явными regex-маркерами, как и остальной текст (см. rules.py,
категории image_*). Специалист в итоге видит не "балл от ИИ", а конкретную
фразу-объяснение и сам пост, и решение всё равно принимает сам, глядя на
исходную картинку.

Без ANTHROPIC_API_KEY анализ просто пропускается (как и с любым другим
внешним токеном в проекте) — вызывающий код в этом случае откатывается на
прежнее поведение («фото — нужен ручной просмотр»)."""

import base64
import json
import logging
import os

logger = logging.getLogger("risk_watchlist.risk_engine.image_analysis")

_MODEL = os.environ.get("IMAGE_ANALYSIS_MODEL", "claude-sonnet-5")

# Фиксированный словарь категорий — модель обязана выбрать одну из них (или
# "none"), а не сформулировать произвольный вывод. Русский текст справа — это
# и есть та самая фраза, по которой сработает regex-маркер в rules.py.
_CATEGORY_LABELS = {
    "weapon": "оружие на фото",
    "nazi_symbol": "нацистская символика на фото",
    "extremist_symbol": "экстремистская символика на фото",
    "violence": "сцена насилия на фото",
}

_PROMPT = """Ты помогаешь специалисту первично отсортировать публичные фото из открытых каналов/групп — не выносишь окончательное решение, а только подсказываешь, на что обратить внимание. Итоговое решение всегда принимает человек, глядя на само фото.

Определи, есть ли на фотографии ЯВНО видимое: огнестрельное/холодное оружие, нацистская символика (свастика и т.п.), другая экстремистская символика/атрибутика, либо сцена насилия.

Ответь СТРОГО в формате JSON, без markdown-разметки и без лишнего текста вокруг:
{"category": "weapon" | "nazi_symbol" | "extremist_symbol" | "violence" | "none", "description": "одно короткое предложение на русском о том, что именно видно на фото"}

Если ничего из перечисленного явно не видно — category должна быть "none". Не додумывай и не предполагай контекст — оценивай только то, что реально видно на изображении."""


def analyze_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict | None:
    """Возвращает {"category", "label", "description"} либо None, если анализ
    недоступен или запрос не удался — тогда вызывающий код сам решает, как
    обработать пост (обычно откатом на «нужен ручной просмотр»)."""

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic
    except ImportError:
        logger.warning("Пакет anthropic не установлен — анализ изображений недоступен.")
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=_MODEL,
            max_tokens=200,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": base64.b64encode(image_bytes).decode("ascii"),
                            },
                        },
                        {"type": "text", "text": _PROMPT},
                    ],
                }
            ],
        )
        raw = response.content[0].text.strip()
        result = json.loads(raw)
    except Exception as exc:
        logger.warning("Анализ изображения не удался: %s", exc)
        return None

    category = result.get("category")
    if category != "none" and category not in _CATEGORY_LABELS:
        logger.warning("Модель вернула неожиданную категорию: %r", category)
        return None

    return {
        "category": category,
        "label": _CATEGORY_LABELS.get(category),
        "description": str(result.get("description") or "").strip(),
    }
