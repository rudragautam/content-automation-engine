"""Page-by-page lists. Each list on a page has its own query parameter, so
several lists on one page can be paged independently and filters stay put."""

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence
from urllib.parse import urlencode


@dataclass
class Page:
    items: List[Any]
    number: int
    pages: int
    total: int
    per_page: int
    param: str
    query: Mapping[str, str]
    anchor: str = ""

    @property
    def start(self) -> int:
        return (self.number - 1) * self.per_page + 1 if self.total else 0

    @property
    def end(self) -> int:
        return min(self.number * self.per_page, self.total)

    def href(self, number: int) -> str:
        query = {k: v for k, v in self.query.items() if k != self.param and v != ""}
        if number > 1:
            query[self.param] = str(number)
        return "?" + urlencode(query) + (f"#{self.anchor}" if self.anchor else "")

    def window(self, around: int = 1) -> List[Optional[int]]:
        """Page numbers to link: first, last and a few around the current one; None marks a gap."""
        keep = {1, self.pages} | set(range(self.number - around, self.number + around + 1))
        numbers, last = [], 0
        for n in sorted(k for k in keep if 1 <= k <= self.pages):
            if n - last > 1:
                numbers.append(None)
            numbers.append(n)
            last = n
        return numbers

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    def __bool__(self):
        return self.total > 0


def paginate(items: Sequence[Any], query: Mapping[str, str], param: str = "page", per_page: int = 20, anchor: str = "") -> Page:
    total = len(items)
    pages = max(1, -(-total // per_page))
    try:
        number = int(query.get(param, 1))
    except (TypeError, ValueError):
        number = 1
    number = min(max(number, 1), pages)
    start = (number - 1) * per_page
    return Page(list(items[start:start + per_page]), number, pages, total, per_page, param, dict(query), anchor)
