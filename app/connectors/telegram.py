"""Готовый коннектор для Telegram — официальный Bot API.

Специалисту нужно завести бота через @BotFather и добавить его администратором
в целевой публичный канал, группу или супергруппу — без прав администратора
Telegram не отдаёт боту сообщения (боты не бывают «обычными участниками» канала;
а в группах права администратора автоматически снимают «приватный режим»
Telegram, при котором бот иначе видит только команды/упоминания, а не все
сообщения). Коннектор читает только то, что Telegram присылает боту официальным
методом getUpdates (события channel_post — посты канала, и message — сообщения
в группе/супергруппе), и никогда не публикует, не удаляет и не пересылает
сообщения от имени бота — метод отправки сообщений (sendMessage) в коде
коннектора вообще не используется.

Коннектор не хранит собственный курсор (offset) в getUpdates — вместо этого,
как и остальные коннекторы в проекте, каждый раз локально фильтрует посты по
дате (`since`) и полагается на дедупликацию по external_id в services/polling.py.
Для небольшого числа наблюдаемых каналов это осознанно простое и надёжное
решение; для очень высокого объёма сообщений в канале эффективнее хранить offset,
но это усложнение оставлено вне рамок референсного коннектора.

Комментарии под постами канала технически устроены в Telegram так: комментарии
у канала возможны только через привязанную к нему группу обсуждений (discussion
group) — сами комментарии физически являются обычными сообщениями в этой группе.
Поэтому при опросе канала коннектор дополнительно узнаёт через getChat, есть ли
у него привязанная группа обсуждений (linked_chat_id), и если да — забирает
сообщения из неё тоже, как комментарии к постам этого источника. Для этого бот
должен быть администратором ОБОИХ чатов: и самого канала, и его группы
обсуждений — это два разных чата с точки зрения Telegram, добавить бота нужно
в каждый по отдельности.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import requests
from pydantic import BaseModel

from app.config import GENERIC_API_TIMEOUT_SECONDS
from app.connectors.base import RawPost
from app.risk_engine import image_analysis

if TYPE_CHECKING:
    from app.models import WatchSource

logger = logging.getLogger("risk_watchlist.connectors.telegram")

TELEGRAM_UPDATES_URL = "https://api.telegram.org/bot{token}/getUpdates"
TELEGRAM_GET_CHAT_URL = "https://api.telegram.org/bot{token}/getChat"
TELEGRAM_GET_FILE_URL = "https://api.telegram.org/bot{token}/getFile"
TELEGRAM_FILE_DOWNLOAD_URL = "https://api.telegram.org/file/bot{token}/{file_path}"
UPDATES_LIMIT = 100


class TelegramConfig(BaseModel):
    auth_env_var: str


def _extract_channel_username(source_identifier: str) -> str:
    value = source_identifier.strip()
    value = re.sub(r"^(https?://)?(www\.)?t\.me/", "", value, flags=re.IGNORECASE)
    value = value.lstrip("@")
    return value.strip("/ ")


class TelegramConnector:
    def fetch_new_posts(self, source: "WatchSource", since: datetime | None) -> list[RawPost]:
        try:
            config = TelegramConfig.model_validate(source.config_json or {})
        except Exception as exc:
            logger.error(
                "Источник %s (id=%s): некорректный config_json для Telegram: %s",
                source.display_name, source.id, exc,
            )
            return []

        token = os.environ.get(config.auth_env_var)
        if not token:
            logger.error(
                "Источник %s (id=%s): переменная окружения %s не задана — опрос Telegram "
                "пропущен для этого источника, остальные продолжают опрашиваться.",
                source.display_name, source.id, config.auth_env_var,
            )
            return []

        channel_username = _extract_channel_username(source.source_identifier)
        if not channel_username:
            logger.error(
                "Источник %s (id=%s): не удалось определить username канала из %r",
                source.display_name, source.id, source.source_identifier,
            )
            return []

        linked_chat_id = _get_linked_chat_id(token, channel_username, source)

        url = TELEGRAM_UPDATES_URL.format(token=token)
        params = {
            "timeout": 0,
            "limit": UPDATES_LIMIT,
            "allowed_updates": json.dumps(["channel_post", "message"]),
        }

        try:
            response = requests.get(url, params=params, timeout=GENERIC_API_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.RequestException as exc:
            logger.error(
                "Источник %s (id=%s): ошибка запроса к Telegram Bot API: %s",
                source.display_name, source.id, exc,
            )
            return []
        except ValueError as exc:
            logger.error(
                "Источник %s (id=%s): ответ Telegram Bot API не является валидным JSON: %s",
                source.display_name, source.id, exc,
            )
            return []

        if not payload.get("ok"):
            logger.error(
                "Источник %s (id=%s): Telegram Bot API вернул ошибку: %s",
                source.display_name, source.id, payload.get("description"),
            )
            return []

        effective_since = since or datetime.fromtimestamp(0, tz=timezone.utc)
        if effective_since.tzinfo is None:
            effective_since = effective_since.replace(tzinfo=timezone.utc)

        posts: list[RawPost] = []
        for update in payload.get("result", []):
            post = update.get("channel_post") or update.get("message")
            if not post:
                continue

            chat = post.get("chat", {})
            chat_username = (chat.get("username") or "").lower()
            is_primary_chat = chat_username == channel_username.lower()
            is_comment = linked_chat_id is not None and chat.get("id") == linked_chat_id
            if not is_primary_chat and not is_comment:
                continue  # апдейт из другого чата того же бота — не этот источник

            post_date = datetime.fromtimestamp(post.get("date", 0), tz=timezone.utc)
            if post_date <= effective_since:
                continue

            caption = (post.get("text") or post.get("caption") or "").strip()
            has_media = _has_media(post)
            if not caption and not has_media:
                continue  # ни текста, ни медиа — служебное сообщение, нечего показывать

            # Автоматическая пересылка поста канала в группу обсуждений тоже
            # приходит как message в этой группе — это дубль самого поста,
            # а не комментарий к нему, пропускаем, чтобы не считать его дважды.
            if is_comment and post.get("is_automatic_forward"):
                continue

            if "photo" in post:
                # Фото — единственный вид медиа, который система умеет читать
                # (через Claude, см. risk_engine/image_analysis.py). Видео,
                # стикеры и голосовые по-прежнему не анализируются.
                analysis_text = _analyze_telegram_photo(token, post["photo"])
                if analysis_text is not None:
                    text = f"{analysis_text} Подпись: {caption}" if caption else analysis_text
                    has_media = False  # уже проверено автоматически, ручной просмотр не обязателен
                else:
                    text = caption or "[фото — не удалось проанализировать автоматически, требуется ручной просмотр]"
            elif not caption:
                # Видео/стикер/голосовое и т.п. система не анализирует (нет
                # такой возможности) — вместо того чтобы молча пропустить
                # пост, помечаем его для ручного просмотра.
                text = "[медиа без подписи — видео/стикер/голосовое, требуется ручной просмотр]"
            else:
                text = caption

            message_id = post.get("message_id")
            author_label = _author_label(post, chat, channel_username)
            if is_comment:
                author_label = f"{author_label} (комментарий)"

            posts.append(
                RawPost(
                    external_id=f"{'comment' if is_comment else 'post'}-{message_id}",
                    text=text,
                    author_label=author_label,
                    published_at=post_date,
                    has_media=has_media,
                )
            )

        return posts


def _get_linked_chat_id(token: str, channel_username: str, source: "WatchSource") -> int | None:
    """Узнаёт id привязанной группы обсуждений канала, если она есть.

    Это дополнительный, необязательный для основной работы запрос: если он не
    удался (сеть, канал не поддерживает комментарии, бот ещё не состоит в
    группе обсуждений) — коннектор просто не будет искать комментарии в этом
    цикле, но посты самого канала/группы всё равно продолжат обрабатываться."""

    try:
        response = requests.get(
            TELEGRAM_GET_CHAT_URL.format(token=token),
            params={"chat_id": f"@{channel_username}"},
            timeout=GENERIC_API_TIMEOUT_SECONDS,
        )
        data = response.json()
    except (requests.exceptions.RequestException, ValueError) as exc:
        logger.warning(
            "Источник %s (id=%s): не удалось проверить группу обсуждений (getChat): %s",
            source.display_name, source.id, exc,
        )
        return None

    if not data.get("ok"):
        return None

    return data.get("result", {}).get("linked_chat_id")


def _analyze_telegram_photo(token: str, photo_sizes: list[dict]) -> str | None:
    """photo_sizes — массив размеров одного и того же фото от Telegram;
    берём самый крупный. Возвращает готовую фразу для текста поста (см.
    rules.py, категории image_*) либо None, если фото скачать/проанализировать
    не удалось — тогда вызывающий код откатывается на «нужен ручной просмотр»."""

    if not photo_sizes:
        return None

    largest = max(photo_sizes, key=lambda p: p.get("file_size", 0))
    image_bytes = _download_telegram_file(token, largest["file_id"])
    if image_bytes is None:
        return None

    result = image_analysis.analyze_image(image_bytes, mime_type="image/jpeg")
    if result is None:
        return None

    if result["category"] == "none":
        return "[Фото проверено автоматически (ИИ) — явных признаков риска не обнаружено.]"
    return f"[Фото проанализировано ИИ: {result['label']}.] {result['description']}"


def _download_telegram_file(token: str, file_id: str) -> bytes | None:
    try:
        response = requests.get(
            TELEGRAM_GET_FILE_URL.format(token=token),
            params={"file_id": file_id},
            timeout=GENERIC_API_TIMEOUT_SECONDS,
        )
        data = response.json()
        if not data.get("ok"):
            logger.warning("Telegram getFile вернул ошибку: %s", data.get("description"))
            return None
        file_path = data["result"]["file_path"]

        file_response = requests.get(
            TELEGRAM_FILE_DOWNLOAD_URL.format(token=token, file_path=file_path),
            timeout=GENERIC_API_TIMEOUT_SECONDS,
        )
        file_response.raise_for_status()
        return file_response.content
    except (requests.exceptions.RequestException, ValueError, KeyError) as exc:
        logger.warning("Не удалось скачать файл из Telegram: %s", exc)
        return None


_MEDIA_KEYS = ("photo", "video", "sticker", "animation", "document", "video_note", "voice")


def _has_media(post: dict) -> bool:
    return any(key in post for key in _MEDIA_KEYS)


def _author_label(post: dict, chat: dict, fallback: str) -> str:
    """Для поста канала автора обычно нет — это публикация от лица самого
    канала. Для сообщения в группе/супергруппе есть конкретный отправитель
    (from) либо, если сообщение отправлено от имени чата анонимным админом —
    sender_chat. Разные источники одного и того же текста должны быть видны
    специалисту, а не свёрнуты в одну обезличенную подпись."""

    from_user = post.get("from")
    if from_user:
        return from_user.get("username") or from_user.get("first_name") or "участник группы"

    sender_chat = post.get("sender_chat")
    if sender_chat:
        return sender_chat.get("title") or sender_chat.get("username") or fallback

    return chat.get("title") or fallback
