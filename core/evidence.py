"""Research evidence model."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Evidence:
    source_url: str
    source_title: str
    publisher: str
    published_at: str | None = None
    extracted_text: str = ""
    retrieved_at: str = ""
