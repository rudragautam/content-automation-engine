"""Shared rules for deciding how long a slide stays on screen.

Durations are derived from what the viewer has to take in on that slide:
words to read, text the template types out, and a short hold at the end.
"""

import re

# On-screen reading speed for a general audience (about 180 words per minute).
READING_WORDS_PER_SECOND = 3.0


# \w alone splits Devanagari words at their vowel signs, so those marks count as word characters too.
WORD = re.compile(r"[\wऀ-ॿ]+")


def word_count(*texts: str) -> int:
    return sum(len(WORD.findall(str(text or ""))) for text in texts)


def reading_seconds(*texts: str, words_per_second: float = READING_WORDS_PER_SECOND) -> float:
    return word_count(*texts) / words_per_second


def typing_seconds(text: str, ms_per_char: int) -> float:
    return len(text or "") * ms_per_char / 1000


def clamp_seconds(value: float, minimum: float, maximum: float) -> float:
    return round(min(max(value, minimum), maximum), 1)
