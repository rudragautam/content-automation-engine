"""Template adapter registry with configs for all functional templates."""

from templates.adapters.base import TemplateAdapter

ADAPTER_CONFIGS = {
    "01_Focus_Habits_Shorts_9x16": {
        "data_var": "slidesData",
        "data_source": "scenes",
        "field_map": {
            "title": "title",
            "text": "text",
        },
        "asset_field": None,
        "theme_vars": (
            "bg", "text", "muted", "glass", "border",
            "accent", "accent-2", "duration",
        ),
        "supported_dynamic_fields": (
            "title", "text", "duration",
        ),
    },
    "02_Geeta_Gyaan_9x16": {
        "data_var": "slidesData",
        "data_source": "scenes",
        "field_map": {
            "chapter": "chapter",
            "title": "title",
            "text": "text",
            "image": "image",
        },
        "asset_field": "image",
        "theme_vars": (
            "bg", "cream", "gold", "muted",
            "image-opacity", "duration",
        ),
        "supported_dynamic_fields": (
            "chapter", "title", "text", "image",
        ),
    },
    "03_General_Quiz_9x16": {
        "data_var": "quizData",
        "data_source": "scenes",
        "field_map": {
            "category": "category",
            "question": "title",
            "text": "explanation",
        },
        "asset_field": None,
        "theme_vars": (),
        "supported_dynamic_fields": (
            "category", "question", "options", "correct", "explanation",
        ),
    },
    "04_Science_Quiz_9x16": {
        "data_var": "quizData",
        "data_source": "scenes",
        "field_map": {
            "category": "category",
            "question": "title",
            "text": "explanation",
        },
        "asset_field": None,
        "theme_vars": (),
        "supported_dynamic_fields": (
            "category", "question", "options", "correct", "explanation",
        ),
    },
    "05_Science_Storytelling_9x16": {
        "data_var": "storyData",
        "data_source": "scenes",
        "field_map": {
            "chapter": "chapter",
            "title": "title",
            "text": "text",
            "image": "image",
            "textPosition": "textPosition",
        },
        "asset_field": "image",
        "theme_vars": (),
        "supported_dynamic_fields": (
            "chapter", "title", "text", "image", "textPosition",
        ),
    },
    "06_Indian_Traditional_Story_9x16": {
        "data_var": "storyData",
        "data_source": "scenes",
        "field_map": {
            "chapter": "chapter",
            "title": "title",
            "text": "text",
            "image": "image",
            "textPosition": "textPosition",
        },
        "asset_field": "image",
        "theme_vars": (),
        "supported_dynamic_fields": (
            "chapter", "title", "text", "image", "textPosition",
        ),
    },
    "07_Indian_Heritage_Story_16x9": {
        "data_var": "storyData",
        "data_source": "scenes",
        "field_map": {
            "chapter": "chapter",
            "title": "title",
            "text": "text",
            "image": "image",
            "textPosition": "textPosition",
        },
        "asset_field": "image",
        "theme_vars": (
            "bg", "cream", "muted", "gold", "gold-light", "saffron", "image-opacity",
        ),
        "supported_dynamic_fields": (
            "chapter", "title", "text", "image", "textPosition",
        ),
    },
    "08_Crime_Files_16x9": {
        "data_var": "crimeData",
        "data_source": "scenes",
        "field_map": {
            "chapter": "chapter",
            "title": "title",
            "text": "text",
            "image": "image",
            "textPosition": "textPosition",
        },
        "asset_field": "image",
        "theme_vars": (
            "bg", "white", "muted", "red", "red-light", "image-opacity",
        ),
        "supported_dynamic_fields": (
            "chapter", "title", "text", "image", "textPosition",
        ),
    },
    "14_AI_Neural_Intelligence_16x9": {
        "data_var": "aiData",
        "data_source": "scenes",
        "field_map": {
            "section": "section",
            "title": "title",
            "narration": "narration",
            "image": "image",
            "textPosition": "textPosition",
            "signal": "signal",
            "sub": "sub",
        },
        "asset_field": "image",
        "theme_vars": (
            "bg", "cyan", "blue", "violet", "white", "muted", "line", "image-opacity",
        ),
        "supported_dynamic_fields": (
            "section", "title", "narration", "image", "textPosition",
            "signal", "sub", "m1", "m2", "m3", "m4",
        ),
    },
    "15_AI_Digital_Future_16x9": {
        "data_var": "aiData",
        "data_source": "scenes",
        "field_map": {
            "section": "section",
            "title": "title",
            "narration": "narration",
            "image": "image",
            "textPosition": "textPosition",
            "metric": "metric",
            "desc": "desc",
        },
        "asset_field": "image",
        "theme_vars": (
            "bg", "pink", "orange", "purple", "cyan", "white", "muted", "line", "image-opacity",
        ),
        "supported_dynamic_fields": (
            "section", "title", "narration", "image", "textPosition",
            "metric", "desc", "bars",
        ),
    },
}


class TemplateAdapterRegistry:
    def __init__(self):
        self._adapters: Dict[str, TemplateAdapter] = {}
        for template_id, config in ADAPTER_CONFIGS.items():
            self._adapters[template_id] = TemplateAdapter(template_id, config)

    def get_adapter(self, template_id: str) -> TemplateAdapter:
        if template_id not in self._adapters:
            raise KeyError(f"No adapter found for template '{template_id}'")
        return self._adapters[template_id]

    def has_adapter(self, template_id: str) -> bool:
        return template_id in self._adapters

    def list_template_ids(self) -> list:
        return list(self._adapters.keys())

    def list_functional(self) -> list:
        return list(self._adapters.keys())
