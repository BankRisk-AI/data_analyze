from app.core.exceptions import AppError


class ProtectedModelError(AppError):
    kind = "model-protected"
    status = 409
    title = "Model cannot be changed"
