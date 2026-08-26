"""Нечёткий поиск фраз-маркеров с допуском на опечатку — «геноцид» находит и
«гиноцид» (одна заменённая буква). Применяется только к маркерам из
custom_markers (ручные из «Правок» + загруженный словарь «Маяк»): у них фраза
— это конкретные слова, а не regex-шаблон, поэтому нечёткое сравнение здесь
уместно и просто. Встроенные маркеры (rules.py) уже ловят словоформы через
regex по корню слова — им фаззи-поиск не нужен.

Допуск на расстояние Левенштейна растёт со длиной слова — иначе длинные слова
(«терроризм», 9 букв) с двумя опечатками («тирраризм») не проходили бы порог
в 1 букву, а короткие слова с тем же относительным допуском начинали бы
находить вообще что попало. Слова короче 4 букв («он», «те», «за») фаззи не
сравниваются вообще — иначе почти любое слово в тексте случайно попадало бы
в радиус одной опечатки от них, и сигналы посыпались бы на пустом месте."""

import re

_MIN_FUZZY_WORD_LENGTH = 4

# С какой длины допуска начинает требоваться дополнительная проверка окончания
# слова (см. _suffix_matches) — при широком допуске (2-3 буквы) один общий
# лимит расстояния уже недостаточно точен: например «террариум» отличается от
# «терроризм» всего на 2 буквы, хотя это совершенно не связанные по смыслу
# слова. Различаются они окончанием («-иум» и «-изм»), поэтому его и проверяем
# отдельно.
_SUFFIX_ANCHOR_FROM_DISTANCE = 2
_SUFFIX_ANCHOR_LENGTH = 3

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def _max_edit_distance_for(word_length: int) -> int:
    """Чем длиннее слово-маркер, тем больше опечаток в нём можно допустить,
    не рискуя случайно попасть в другое слово: 4–7 букв — 1 опечатка (как
    «геноцид»/«гиноцид»), 8 букв — 2, 9+ букв — 3 (у «терроризма», 9 букв,
    на практике встречаются варианты аж с тремя опечатками: «тирраризм»,
    «тираризм»). Расстояние 3 для 9-буквенных слов проверено на соседних по
    написанию, но не связанных по смыслу словах («территория», «терапия»,
    «тираж» и т.п.) — у всех расстояние до «терроризм» оказалось 4+, то есть
    в этот допуск они не попадают."""
    if word_length >= 9:
        return 3
    if word_length >= 8:
        return 2
    return 1


def _suffix_matches(text_word: str, marker_word: str) -> bool:
    """При широком допуске опечаток одного общего расстояния мало — оно
    позволяет опечатке «съесть» любую часть слова, включая окончание, из-за
    чего в допуск начинают попадать случайные слова с тем же корнем, но другим
    окончанием («террариум» при допуске 2 иначе прошёл бы как «терроризм»).
    Реальные опечатки почти всегда правят середину слова, а не переписывают
    конец, поэтому требуем точного совпадения последних букв."""
    if len(text_word) < _SUFFIX_ANCHOR_LENGTH or len(marker_word) < _SUFFIX_ANCHOR_LENGTH:
        return True
    return text_word[-_SUFFIX_ANCHOR_LENGTH:] == marker_word[-_SUFFIX_ANCHOR_LENGTH:]


def _words_fuzzy_equal(text_word: str, marker_word: str) -> bool:
    if text_word == marker_word:
        return True
    if len(marker_word) < _MIN_FUZZY_WORD_LENGTH:
        return False
    max_distance = _max_edit_distance_for(len(marker_word))
    # Явная отсечка по длине — не тратить Левенштейн на заведомо непохожие слова.
    if abs(len(text_word) - len(marker_word)) > max_distance:
        return False
    if max_distance >= _SUFFIX_ANCHOR_FROM_DISTANCE and not _suffix_matches(text_word, marker_word):
        return False
    return _levenshtein(text_word, marker_word) <= max_distance


def fuzzy_phrase_search(text_tokens: list[re.Match], text: str, phrase: str) -> str | None:
    """text_tokens — результат _WORD_RE.finditer(text.lower()), посчитанный один
    раз на пост и переиспользуемый для всех маркеров (иначе токенизация текста
    заново на каждый из 200+ маркеров была бы лишней работой).

    Возвращает найденный фрагмент ИЗ ОРИГИНАЛЬНОГО текста (с сохранением
    регистра — для подсветки и отображения специалисту), либо None."""

    # Фраза токенизируется тем же \w+, что и текст поста (а не простым split()
    # по пробелу) — иначе слова с апострофом вроде "i'll" расходятся с тем, как
    # \w+ режет тот же апостроф в тексте, и совпадение никогда не находится.
    phrase_words = [m.group() for m in _WORD_RE.finditer(phrase.lower())]
    if not phrase_words:
        return None

    n = len(phrase_words)
    for i in range(len(text_tokens) - n + 1):
        window = text_tokens[i : i + n]
        if all(_words_fuzzy_equal(tok.group(), pw) for tok, pw in zip(window, phrase_words)):
            start, end = window[0].start(), window[-1].end()
            return text[start:end]
    return None


def tokenize(text_lower: str) -> list[re.Match]:
    return list(_WORD_RE.finditer(text_lower))
