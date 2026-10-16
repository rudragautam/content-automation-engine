"""Maps template IDs to their workflows."""

from typing import Dict, Type

from workflows.base import TemplateWorkflow
from workflows.focus_habits import FocusHabitsWorkflow
from workflows.slides import (
    AIDigitalFutureWorkflow,
    AINeuralIntelligenceWorkflow,
    CrimeFilesWorkflow,
    GeetaGyaanWorkflow,
    GeneralQuizWorkflow,
    IndianHeritageStoryWorkflow,
    IndianTraditionalStoryWorkflow,
    ScienceQuizWorkflow,
    ScienceStoryWorkflow,
)

WORKFLOWS: Dict[str, Type[TemplateWorkflow]] = {
    w.template_id: w
    for w in (
        FocusHabitsWorkflow,
        GeetaGyaanWorkflow,
        GeneralQuizWorkflow,
        ScienceQuizWorkflow,
        ScienceStoryWorkflow,
        IndianTraditionalStoryWorkflow,
        IndianHeritageStoryWorkflow,
        CrimeFilesWorkflow,
        AINeuralIntelligenceWorkflow,
        AIDigitalFutureWorkflow,
    )
}


def has_workflow(template_id: str) -> bool:
    return template_id in WORKFLOWS


def get_workflow(template_id: str) -> TemplateWorkflow:
    if template_id not in WORKFLOWS:
        raise KeyError(f"No workflow for template '{template_id}'")
    return WORKFLOWS[template_id]()
