from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("linkedin_scraper")


def send_email_report(
    html_content: str,
    to_addr: str,
    from_addr: str,
    password: str,
    subject: str = "LinkedIn Post Intelligence Report",
) -> bool:
    """
    Send the HTML report via Gmail SMTP (SSL).

    Requires a Gmail App Password (not the account password).
    See: https://support.google.com/accounts/answer/185833
    """
    if not to_addr or not from_addr or not password:
        logger.error("Email send skipped: missing to_addr, from_addr, or password")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(from_addr, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
        logger.info(f"Email report sent to {to_addr}")
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Email authentication failed. Ensure you are using a Gmail App Password, "
            "not your account password. See https://support.google.com/accounts/answer/185833"
        )
        return False
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return False
