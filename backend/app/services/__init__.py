class DomainError(Exception):
    """A refusal the user can act on. ``code`` maps to a message in the frontend."""

    status = 400

    def __init__(self, code: str, status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        if status is not None:
            self.status = status


class NotFound(DomainError):
    status = 404


class Forbidden(DomainError):
    status = 403


class Conflict(DomainError):
    status = 409
