import json
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CustomMarker, Post, RiskSignal
from app.risk_engine.scorer import score_post
from app.risk_engine.translit import contains_cyrillic, transliterate_variants

MIN_WEIGHT = 0.1
MAX_WEIGHT = 6.0

_RISK_ENGINE_DIR = Path(__file__).resolve().parent.parent / "risk_engine"
MAYAK_DICTIONARY_PATH = _RISK_ENGINE_DIR / "mayak_dictionary.json"
MAYAK_DICTIONARY_EN_PATH = _RISK_ENGINE_DIR / "mayak_dictionary_en.json"


MANUAL_SOURCE = "Добавлено специалистом вручную"


def list_markers(db: Session) -> list[CustomMarker]:
    return list(db.scalars(select(CustomMarker).order_by(CustomMarker.added_at.desc())))


def list_manual_markers(db: Session) -> list[CustomMarker]:
    """Только добавленные вручную через чат «Правки» — для показа как переписки."""
    return [m for m in list_markers(db) if m.source == MANUAL_SOURCE]


def list_dictionary_groups(db: Session) -> list[dict]:
    """Загруженные из словаря маркеры, сгруппированные по категории — 213 отдельных
    «сообщений в чате» были бы нечитаемы, поэтому здесь сводка: категория, вес,
    источник, объяснение и список слов/фраз в ней."""
    groups: dict[str, dict] = {}
    for m in list_markers(db):
        if m.source == MANUAL_SOURCE or not m.source:
            continue
        g = groups.setdefault(
            m.category,
            {"category_title": m.category_title or m.category, "weight": m.weight, "source": m.source, "note": m.note, "terms": []},
        )
        g["terms"].append(m.phrase)
    return sorted(groups.values(), key=lambda g: g["category_title"])


def as_extra_markers(db: Session) -> list[dict]:
    """Формат, который принимает risk_engine.scorer.score_post(extra_markers=...).

    category — ключ группировки при скоринге (см. scorer.py): для записей из
    словаря это настоящая категория (recruitment, planning и т.д.), для ручных
    записей из «Правок» — сама фраза, чтобы каждая считалась независимо.

    Для каждого кириллического маркера дополнительно добавляются его
    транслит-варианты латиницей («геноцид» → «genotsid» И «genocid» —
    неоднозначные буквы вроде «ц» дают оба распространённых написания, а
    дальше нечёткий поиск добирает мелкую разницу вплоть до настоящего
    английского слова «genocide»). У всех вариантов та же category, что у
    оригинала, поэтому на балл они влияют как ОДНО совпадение, сколько бы их
    ни было и что бы из них ни нашлось в посте."""

    markers = []
    for m in list_markers(db):
        description = f"{m.note} — «{m.phrase}»" if m.note else f"«{m.phrase}» — добавлено специалистом"
        markers.append({"category": m.category, "description": description, "weight": m.weight, "phrase": m.phrase})

        if contains_cyrillic(m.phrase):
            for translit_phrase in transliterate_variants(m.phrase):
                markers.append(
                    {
                        "category": m.category,
                        "description": f"{description} (латиницей: «{translit_phrase}»)",
                        "weight": m.weight,
                        "phrase": translit_phrase,
                    }
                )

    return markers


def add_marker(db: Session, *, phrase: str, weight: float, added_by: str) -> tuple[CustomMarker, int]:
    """Добавляет слово-маркер вручную (вкладка «Правки») и сразу пересчитывает
    уже накопленные посты без сигнала — чтобы специалист сразу увидел эффект,
    а не ждал, пока что-то новое придёт с платформы. Возвращает (маркер,
    сколько новых сигналов появилось при пересчёте).

    category = сама фраза: у ручных маркеров нет общей смысловой категории
    друг с другом (в отличие от словарных), поэтому каждый должен считаться
    независимо в scorer.py, а не группироваться с другими ручными записями."""

    phrase = phrase.strip()
    if not phrase:
        raise ValueError("Слово или фраза не может быть пустой")
    if not (MIN_WEIGHT <= weight <= MAX_WEIGHT):
        raise ValueError(f"Вес должен быть от {MIN_WEIGHT} до {MAX_WEIGHT}")

    marker = CustomMarker(
        phrase=phrase,
        category=phrase,
        weight=weight,
        source="Добавлено специалистом вручную",
        added_by=added_by.strip(),
    )
    db.add(marker)
    db.commit()
    db.refresh(marker)

    matches = _rescan_existing_posts(db)

    return marker, matches


def delete_marker(db: Session, marker_id: int) -> None:
    marker = db.get(CustomMarker, marker_id)
    if marker is None:
        raise ValueError(f"Маркер id={marker_id} не найден")
    db.delete(marker)
    db.commit()


def load_mayak_dictionary(db: Session, *, added_by: str) -> tuple[int, int]:
    """Массово загружает словарь «Маяк» — русскую версию (mayak_dictionary.json)
    и англоязычные эквиваленты тех же 12 категорий (mayak_dictionary_en.json,
    те же обобщённые слова-концепты вербовки/секретности/давления и т.д.,
    просто на другом языке, а не новые категории) — структура записей одна и
    та же: {term, category, weight, source, explanation}. Категории совпадают
    с русской версией (category: "planning" и там, и там), поэтому дедупликация
    по категории в scorer.py работает одинаково независимо от языка поста.

    Пропускает записи, уже загруженные ранее (по паре phrase+category), чтобы
    повторный запуск не плодил дубли. Возвращает (сколько добавлено, сколько
    сигналов найдено при пересчёте уже накопленных постов)."""

    entries = []
    for path in (MAYAK_DICTIONARY_PATH, MAYAK_DICTIONARY_EN_PATH):
        if path.exists():
            with open(path, encoding="utf-8") as f:
                entries.extend(json.load(f))

    existing = {(m.phrase, m.category) for m in list_markers(db)}

    added = 0
    for entry in entries:
        key = (entry["term"], entry["category"])
        if key in existing:
            continue
        db.add(
            CustomMarker(
                phrase=entry["term"],
                category=entry["category"],
                category_title=entry.get("category_title", entry["category"]),
                weight=entry["weight"],
                source=entry.get("source", ""),
                note=entry.get("explanation", ""),
                added_by=added_by,
            )
        )
        existing.add(key)
        added += 1
    db.commit()

    matches = _rescan_existing_posts(db) if added else 0
    return added, matches


def _rescan_existing_posts(db: Session) -> int:
    """Пересчитывает уже накопленные посты без сигнала под ПОЛНЫЙ текущий
    набор маркеров (встроенные + все пользовательские) — так, если несколько
    добавленных слов вместе перекрывают порог, это тоже будет учтено."""

    posts_without_signal = db.scalars(
        select(Post).outerjoin(RiskSignal).where(RiskSignal.id.is_(None))
    ).all()
    extra = as_extra_markers(db)

    created = 0
    for post in posts_without_signal:
        assessment = score_post(post.text, extra_markers=extra)
        if assessment.level is not None:
            db.add(
                RiskSignal(
                    post_id=post.id,
                    score=assessment.score,
                    level=assessment.level,
                    matched_markers=[asdict(m) for m in assessment.matched_markers],
                )
            )
            created += 1
    db.commit()
    return created
