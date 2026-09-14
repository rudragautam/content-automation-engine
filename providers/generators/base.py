"""Content generator interface."""

from abc import ABC, abstractmethod

from core.briefing import ContentBrief, ContentItem


class ContentGenerator(ABC):
    @abstractmethod
    def generate(self, brief: ContentBrief) -> ContentItem:
        pass
