"""Stable, client-safe application error codes."""
class ToolError(Exception):
    code = "TOOL_ERROR"
    def __init__(self, message):
        super().__init__(message)
        self.message = message
    def as_dict(self):
        return {"code": self.code, "message": self.message}

class ScopeDeniedError(ToolError):
    code = "SCOPE_DENIED"
class ApprovalRequiredError(ToolError):
    code = "APPROVAL_REQUIRED"
class NotFoundError(ToolError):
    code = "NOT_FOUND"
class InvalidInputError(ToolError):
    code = "INVALID_INPUT"
class PolicyDeniedError(ToolError):
    code = "POLICY_DENIED"
