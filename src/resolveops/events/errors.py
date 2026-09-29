class EventInterfaceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class WebhookAuthenticationError(EventInterfaceError):
    pass


class EventConflictError(EventInterfaceError):
    pass
