class OperationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AuthorizationError(OperationError):
    pass


class ApprovalRequiredError(OperationError):
    pass


class BusinessRuleError(OperationError):
    pass


class ResourceNotFoundError(OperationError):
    pass


class IdempotencyConflictError(OperationError):
    pass


class OperationInProgressError(OperationError):
    pass


class PreviousOperationFailedError(OperationError):
    pass


class VerificationError(OperationError):
    pass


class TransientOperationError(OperationError):
    """A temporary failure that is safe to retry with the same operation identity."""


class OperationTimeoutError(TransientOperationError):
    pass


class RetryExhaustedError(OperationError):
    pass


class RecoveryRequiredError(OperationError):
    pass
