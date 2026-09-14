"""Template exceptions."""


class TemplateError(Exception):
    pass


class TemplateNotFoundError(TemplateError):
    pass


class TemplateUnavailableError(TemplateError):
    pass


class TemplateIncompatibleError(TemplateError):
    pass


class TemplateAdapterError(TemplateError):
    pass
