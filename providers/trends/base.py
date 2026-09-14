"""Trends provider interface."""

from abc import ABC, abstractmethod
from typing import List

from core.models import TrendItem


class TrendsProvider(ABC):
    @abstractmethod
    def fetch(self) -> List[TrendItem]:
        pass
