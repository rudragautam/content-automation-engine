"""Research provider interface."""

from abc import ABC, abstractmethod
from typing import List

from core.evidence import Evidence


class ResearchProvider(ABC):
    @abstractmethod
    def fetch(self, topic: str) -> List[Evidence]:
        pass
