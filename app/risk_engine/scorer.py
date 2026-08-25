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
    weight: int
    matched_keyword: str


@dataclass(frozen=True)
class RiskAssessment:
    score: int
    level: str | None  # None, если ни один маркер не сработал — сигнал не создаётся
    matched_markers: list[MatchedMarker]


def score_post(text: str) -> RiskAssessment:
    """Явный, объяснимый скоринг: по каждой категории — не больше одного
    засчитанного совпадения (чтобы несколько похожих фраз в одном посте не
    раздували балл), но в объяснении видно, какой именно фрагмент сработал.

    Маркеры — regex-шаблоны по корню слова (см. rules.py), а не жёстко заданные
    фразы целиком, поэтому ловятся разные словоформы («устрою»/«устроим»,
    «готов»/«готова»/«готовы» и т.д.) без необходимости перечислять их вручную."""

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
