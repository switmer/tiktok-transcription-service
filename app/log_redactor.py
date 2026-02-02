"""Log redaction formatter — masks phone numbers and Twilio SIDs in all log output."""

import logging
import re

# Phone: +1XXXXXXXXXX or 10-15 digit sequences → ***{last4}
_PHONE_RE = re.compile(r'\+?1?\d{10,14}')

# Twilio SIDs: SM/MM followed by 32 hex chars
_SID_RE = re.compile(r'(SM|MM)[a-f0-9]{32}', re.IGNORECASE)


def _redact_phone(match: re.Match) -> str:
    digits = match.group()
    return f"***{digits[-4:]}"


def _redact_sid(match: re.Match) -> str:
    sid = match.group()
    return f"{sid[:4]}...{sid[-4:]}"


def redact(message: str) -> str:
    """Apply all redaction rules to a log message."""
    message = _SID_RE.sub(_redact_sid, message)
    message = _PHONE_RE.sub(_redact_phone, message)
    return message


class RedactingFormatter(logging.Formatter):
    """Logging formatter that redacts sensitive data from log messages."""

    def format(self, record: logging.LogRecord) -> str:
        original = super().format(record)
        return redact(original)
