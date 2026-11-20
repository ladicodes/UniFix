from __future__ import annotations

import logging

import pytest

from app.core.config import EmailBackend, Environment, Settings, SmtpTlsMode
from app.core.email import ConsoleEmailSender, OutgoingEmail, SmtpEmailSender, build_email_sender
from app.core.logging import RedactingFilter, redact


@pytest.mark.parametrize(
    ("raw", "secret"),
    [
        ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def", "eyJhbGciOiJIUzI1NiJ9"),
        ("GET /api/v1/ws/conversations/1?ticket=abcDEF123_-", "abcDEF123_-"),
        ("link https://x/reset-password?token=SECRETTOKEN123", "SECRETTOKEN123"),
        ('{"password": "hunter2hunter2"}', "hunter2hunter2"),
        ('{"new_password":"s3cr3t-value"}', "s3cr3t-value"),
        ("Cookie: __Secure-unifix_rt=rawrefreshvalue; other=1", "rawrefreshvalue"),
        ("signed_xdr=AAAAAgAAAAB", "AAAAAgAAAAB"),
        (
            "operator SAKICEVQLYWGSOJS4WW7HZJWAHZVEEBS527LHK5V4MLJALYKICQCJXMW loaded",
            "SAKICEVQLYWGSOJS4WW7HZJWAHZVEEBS527LHK5V4MLJALYKICQCJXMW",
        ),
        ('{"escrow_id_secret": "abc-123-def"}', "abc-123-def"),
    ],
)
def test_redaction_removes_secrets(raw: str, secret: str) -> None:
    redacted = redact(raw)
    assert secret not in redacted
    assert "[REDACTED]" in redacted


def test_redacting_filter_rewrites_records() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "token=%s", ("abcdefghijkl",), None)
    RedactingFilter().filter(record)
    assert record.getMessage() == "token=[REDACTED]"


SMTP_SETTINGS = Settings(
    _env_file=None,  # type: ignore[call-arg]
    database_url="postgresql+psycopg://u:p@localhost/db",
    jwt_secret="s" * 40,
    email_backend=EmailBackend.SMTP,
    smtp_host="smtp.example.com",
    smtp_port=465,
    smtp_tls_mode=SmtpTlsMode.TLS,
    email_from="UniFix <no-reply@unifix.ng>",
)


def test_email_backend_selection() -> None:
    assert isinstance(build_email_sender(SMTP_SETTINGS), SmtpEmailSender)
    console = SMTP_SETTINGS.model_copy(
        update={"email_backend": EmailBackend.CONSOLE, "env": Environment.DEVELOPMENT}
    )
    assert isinstance(build_email_sender(console), ConsoleEmailSender)
    production_console = console.model_copy(update={"env": Environment.PRODUCTION})
    with pytest.raises(RuntimeError):
        build_email_sender(production_console)


def test_smtp_message_construction() -> None:
    message = SmtpEmailSender(SMTP_SETTINGS).build(
        OutgoingEmail(to="ada@example.com", subject="Hi", text_body="Body")
    )
    assert message["From"] == "UniFix <no-reply@unifix.ng>"
    assert message["To"] == "ada@example.com"
    assert message["Subject"] == "Hi"
    assert message.get_content().strip() == "Body"
