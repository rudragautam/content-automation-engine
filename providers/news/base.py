"""News provider interface."""

from abc import ABC, abstractmethod
from typing import List

from core.models import NewsItem


class NewsProvider(ABC):
    @abstractmethod
    def fetch(self) -> List[NewsItem]:
        pass
