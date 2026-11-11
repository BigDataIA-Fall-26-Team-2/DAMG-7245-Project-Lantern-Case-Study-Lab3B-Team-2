from pydantic import ValidationError

from creditwatch.channel import ScopeError, require_scope

from .errors import (
    InvalidInputError,
    NotFoundError,
    ScopeDeniedError,
)
from .schemas import ScopeInput, MandateProfileOutput


def read_mandate_profile(payload, *, session, ledger, mandates):
    # 1. Validate the request's structure.
    try:
        request = ScopeInput.model_validate(payload)
    except ValidationError as exc:
        raise InvalidInputError(
            "Expected a nonempty string scope and no extra fields."
        ) from exc

    # 2. Enforce access before looking up client data.
    try:
        require_scope(
            session,
            request.scope,
            "mandate",
            ledger,
        )
    except ScopeError as exc:
        raise ScopeDeniedError(
            "This session cannot access the requested mandate."
        ) from exc

    # 3. Find the authorized client's data.
    mandate = mandates.get(request.scope)
    if mandate is None:
        raise NotFoundError("The active mandate was not found.")

    # 4. Validate and return only the intended fields.
    result = MandateProfileOutput(
        client=mandate["client"],
        positions=mandate["positions"],
    )

    ledger.record(
        "tool_call",
        tool="mandate_profile",
        scope=request.scope,
        decision="executed",
    )

    return result