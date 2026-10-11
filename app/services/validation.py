from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.schemas import RecipientIn


@dataclass
class RecipientResult:
    index: int
    # Raw values as submitted, kept so invalid rows can still be reported.
    raw_name: str | None
    raw_email: str | None
    recipient: RecipientIn | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.recipient is not None and not self.errors


def _format_errors(exc: ValidationError) -> list[str]:
    messages = []
    for err in exc.errors():
        location = ".".join(str(part) for part in err["loc"]) or "recipient"
        messages.append(f"{location}: {err['msg']}")
    return messages


def _raw_str(data: Any, key: str) -> str | None:
    if not isinstance(data, dict) or data.get(key) is None:
        return None
    return str(data[key])[:255]


def validate_recipients(raw_recipients: list[Any]) -> list[RecipientResult]:
    """Validate every recipient independently.

    Returns one result per input row, in the same order. Invalid rows carry
    their error messages instead of raising, so the caller can accept the
    valid rows and report the rest.
    """
    results: list[RecipientResult] = []
    seen_emails: dict[str, int] = {}

    for index, data in enumerate(raw_recipients):
        result = RecipientResult(
            index=index,
            raw_name=_raw_str(data, "name"),
            raw_email=_raw_str(data, "email"),
        )

        if not isinstance(data, dict):
            result.errors.append("recipient: must be an object with 'name' and 'email'")
            results.append(result)
            continue

        try:
            result.recipient = RecipientIn.model_validate(data)
        except ValidationError as exc:
            result.errors.extend(_format_errors(exc))
            results.append(result)
            continue

        # The same person should not receive two certificates in one job.
        email_key = result.recipient.email.lower()
        if email_key in seen_emails:
            result.errors.append(
                f"email: duplicate of recipient at index {seen_emails[email_key]}"
            )
        else:
            seen_emails[email_key] = index

        results.append(result)

    return results
