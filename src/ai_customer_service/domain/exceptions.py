class DomainError(Exception):
    """Base domain exception."""


class OrderNotFoundError(DomainError):
    def __init__(self, order_id: str) -> None:
        super().__init__(f"Order '{order_id}' not found")
        self.order_id = order_id


class OrderAccessDeniedError(DomainError):
    def __init__(self, order_id: str, user_id: str) -> None:
        super().__init__(f"User '{user_id}' cannot access order '{order_id}'")


class InvalidOrderActionError(DomainError):
    """Raised when a requested order action is not permitted under current state.

    Attributes:
        action: the action name that was attempted
        user_reason: user-facing Chinese explanation (used directly in reply messages)
    """

    def __init__(self, action: str, user_reason: str) -> None:
        super().__init__(f"Cannot perform '{action}': {user_reason}")
        self.action = action
        self.user_reason = user_reason


class SafetyViolationError(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"Safety check failed: {reason}")
        self.reason = reason


class HITLRequiredError(DomainError):
    """Raised to signal that interrupt() was called and HITL is pending."""

    def __init__(self, pending_action: dict) -> None:
        super().__init__("Human-in-the-loop approval required")
        self.pending_action = pending_action


class LLMError(DomainError):
    """Raised when the LLM returns an unexpected or malformed response."""
