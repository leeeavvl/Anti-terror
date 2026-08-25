import re
from dataclasses import dataclass

from app.config import RISK_THRESHOLDS
from app.risk_engine.rules import MARKERS

_COMPILED_MARKERS = [
    {**marker, "compiled": [re.compile(pattern, re.IGNORECASE) for pattern in marker["patterns"]]}
    for marker in MARKERS
]


@dataclass(frozen=True)
class MatchedMarker:
    category: str
    description: str
    weight: float
    matched_keyword: str


@dataclass(frozen=True)
class RiskAssessment:
    score: float
    level: str | None  # None, если ни один маркер не сработал — сигнал не создаётся
    matched_markers: list[MatchedMarker]


def score_post(text: str, extra_markers: list[dict] | None = None) -> RiskAssessment:
    """Явный, объяснимый скоринг: по каждой категории — не больше одного
    засчитанного совпадения (чтобы несколько похожих фраз в одном посте не
    раздували балл), но в объяснении видно, какой именно фрагмент сработал.

    Маркеры — regex-шаблоны по корню слова (см. rules.py), а не жёстко заданные
    фразы целиком, поэтому ловятся разные словоформы («устрою»/«устроим»,
    «готов»/«готова»/«готовы» и т.д.) без необходимости перечислять их вручную.

    extra_markers — слова-маркеры, добавленные специалистом вручную через
    вкладку «Правки» либо загруженные из словаря (см. services/custom_markers.py);
    каждый — точная фраза (без учёта регистра), а не regex-шаблон, чтобы
    специалисту не нужно было разбираться в регулярных выражениях. Как и для
    встроенных маркеров, на категорию засчитывается не больше одного
    совпадения — иначе несколько слов одной темы («время», «место», «план» —
    все из категории planning) раздували бы балл суммированием весов."""

    matched: list[MatchedMarker] = []

    for marker in _COMPILED_MARKERS:
        for pattern in marker["compiled"]:
            match = pattern.search(text)
            if match:
                matched.append(
                    MatchedMarker(
                        category=marker["category"],
                        description=marker["description"],
                        weight=marker["weight"],
                        matched_keyword=match.group(0),
                    )
                )
                break

    text_lower = text.lower()
    seen_extra_categories: set[str] = set()
    for marker in extra_markers or []:
        category = marker["category"]
        if category in seen_extra_categories:
            continue
        phrase_lower = marker["phrase"].lower()
        idx = text_lower.find(phrase_lower)
        if idx != -1:
            matched.append(
                MatchedMarker(
                    category=category,
                    description=marker["description"],
                    weight=marker["weight"],
                    matched_keyword=text[idx : idx + len(marker["phrase"])],
                )
            )
            seen_extra_categories.add(category)

    score = sum(m.weight for m in matched)

    if score == 0:
        level = None
    elif score >= RISK_THRESHOLDS["high"]:
        level = "high"
    elif score >= RISK_THRESHOLDS["medium"]:
        level = "medium"
    else:
        level = "low"

    return RiskAssessment(score=score, level=level, matched_markers=matched)
