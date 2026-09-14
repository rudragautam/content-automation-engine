from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class PipelineContext:
    payload: Any

class ContentAutomationPipeline:
    def run(self, context: PipelineContext) -> PipelineContext:
        return context
