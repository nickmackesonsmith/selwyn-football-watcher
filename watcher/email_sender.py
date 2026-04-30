"""
Gmail SMTP email sender.

Uses an App Password (not your account password).
Generate at: https://myaccount.google.com/apppasswords
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

RECIPIENT = "nickmackesonsmith@gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def _get_credentials() -> tuple[str, str]:
    """Read Gmail credentials from environment variables (GitHub Actions secrets)."""
    user = os.environ.get("GMAIL_USER", "").strip()
    password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    if not user or not password:
        raise EnvironmentError("GMAIL_USER and GMAIL_APP_PASSWORD must be set")
    return user, password


def send_email(
    subject: str,
    body_markdown: str,
    high_importance: bool = False,
    test_mode: bool = False,
) -> None:
    """
    Send an email to Nick.

    Args:
        subject: Email subject line.
        body_markdown: Plain-text body (markdown-ish, renders fine in Gmail).
        high_importance: If True, sets X-Priority: 1 and Importance: High.
        test_mode: If True, prepends [TEST] to the subject.
    """
    if test_mode:
        subject = f"[TEST] {subject}"

    user, password = _get_credentials()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = RECIPIENT
    if high_importance:
        msg["X-Priority"] = "1"
        msg["Importance"] = "High"

    # Plain text part
    text_part = MIMEText(body_markdown, "plain", "utf-8")
    msg.attach(text_part)

    # HTML part — convert markdown-style code blocks and bold to HTML
    html_body = _markdown_to_html(body_markdown)
    html_part = MIMEText(html_body, "html", "utf-8")
    msg.attach(html_part)

    logger.info("Sending email: %s", subject)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(user, password)
        server.sendmail(user, RECIPIENT, msg.as_string())
    logger.info("Email sent successfully")


def send_health_alert(subject: str, detail: str) -> None:
    """Send a quiet health/failure alert email."""
    try:
        send_email(
            subject=f"[WATCHER] {subject}",
            body_markdown=detail,
            high_importance=False,
        )
    except Exception as exc:
        logger.error("Could not send health alert: %s", exc)


def _markdown_to_html(text: str) -> str:
    """
    Very minimal markdown → HTML conversion for email readability.
    Handles: **bold**, ```code blocks```, --- separators, line breaks.
    """
    import re
    lines = text.split("\n")
    html_lines = []
    in_code = False

    for line in lines:
        if line.strip() == "```":
            if in_code:
                html_lines.append("</pre>")
                in_code = False
            else:
                html_lines.append(
                    '<pre style="background:#f4f4f4;padding:12px;border-radius:6px;'
                    'font-family:monospace;font-size:14px;white-space:pre-wrap;">'
                )
                in_code = True
            continue

        if in_code:
            html_lines.append(line)
            continue

        if line.strip() == "---":
            html_lines.append("<hr>")
            continue

        # Bold
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        # Italic (used for group name hints)
        line = re.sub(r"_\((.+?)\)_", r"<em>(\1)</em>", line)

        html_lines.append(line + "<br>")

    if in_code:
        html_lines.append("</pre>")

    body = "\n".join(html_lines)
    return f"""
<html><body style="font-family:sans-serif;font-size:15px;line-height:1.6;max-width:700px;margin:auto;padding:20px;">
{body}
</body></html>
"""
