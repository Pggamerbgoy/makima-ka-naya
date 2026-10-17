"""
Makima v2 — Multi-Platform Gateway: Email Adapter Daemon.
Architectural Pattern: Stdlib imaplib / smtplib asynchronous polling daemon with GatewaySecurityManager authorization.
Zero-Hardcoding Guarantee: Fully dynamic connection configuration via environment / MakimaConfig.
Library-First: Direct use of Python stdlib 'email', 'imaplib', 'smtplib', and 'ssl'.
"""

from __future__ import annotations

import asyncio
import email
import email.utils
import imaplib
import logging
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Union

from makima.gateway.adapters.base import BaseAdapter

if TYPE_CHECKING:
    from makima.core.engine import HermesAgentEngine
    from makima.gateway.security import GatewaySecurityManager

logger = logging.getLogger("makima.gateway.adapters.email")


PAIRING_CODE_REGEX = re.compile(r"\b(MK-[A-Z0-9]{4})\b", re.IGNORECASE)


def parse_email_message(raw_bytes: bytes) -> Dict[str, Any]:
    """
    Parses raw RFC822 email bytes into structured metadata and plain text content.
    Extracts From, Subject, Message-ID, and decodes multipart or text bodies.
    """
    msg = email.message_from_bytes(raw_bytes)

    # 1. Headers
    from_raw = msg.get("From", "")
    from_name, from_email = email.utils.parseaddr(from_raw)
    subject = msg.get("Subject", "").strip()
    message_id = msg.get("Message-ID", "").strip()

    # 2. Extract Body (Prefer text/plain)
    body_text = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            if content_type == "text/plain" and "attachment" not in content_disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        body_text = payload.decode(charset, errors="replace")
                        break
                    except Exception:
                        body_text = payload.decode("utf-8", errors="replace")
                        break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            try:
                body_text = payload.decode(charset, errors="replace")
            except Exception:
                body_text = payload.decode("utf-8", errors="replace")

    return {
        "from_raw": from_raw,
        "from_name": from_name,
        "from_email": from_email.lower().strip(),
        "subject": subject,
        "message_id": message_id,
        "body": body_text.strip(),
        "raw_message": msg,
    }


class EmailAdapter(BaseAdapter):
    """
    Production-grade Email Adapter operating as an IMAP polling / SMTP delivery daemon.
    Enforces sender email authorization and ephemeral pairing code verification.
    """

    def __init__(
        self,
        imap_host: Optional[str] = None,
        imap_port: Optional[int] = None,
        imap_ssl: bool = True,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_ssl: bool = False,
        smtp_starttls: bool = True,
        username: Optional[str] = None,
        password: Optional[str] = None,
        from_address: Optional[str] = None,
        poll_interval_seconds: float = 30.0,
        security_manager: Optional[GatewaySecurityManager] = None,
        engine: Optional[HermesAgentEngine] = None,
        imap_factory: Optional[Callable[[], Any]] = None,
        smtp_factory: Optional[Callable[[], Any]] = None,
    ):
        super().__init__(security_manager=security_manager, engine=engine)

        # Connection credentials (with dynamic fallback to environment)
        self.imap_host = imap_host or os.getenv("IMAP_SERVER") or os.getenv("IMAP_HOST") or "localhost"
        self.imap_port = imap_port or int(os.getenv("IMAP_PORT", "993"))
        self.imap_ssl = imap_ssl

        self.smtp_host = smtp_host or os.getenv("SMTP_SERVER") or os.getenv("SMTP_HOST") or "localhost"
        self.smtp_port = smtp_port or int(os.getenv("SMTP_PORT", "587"))
        self.smtp_ssl = smtp_ssl
        self.smtp_starttls = smtp_starttls

        self.username = username or os.getenv("EMAIL_USER") or os.getenv("EMAIL_USERNAME") or ""
        self.password = password or os.getenv("EMAIL_PASSWORD") or os.getenv("EMAIL_PASS") or ""
        self.from_address = from_address or os.getenv("EMAIL_FROM") or self.username or "makima@localhost"

        self.poll_interval = poll_interval_seconds
        self._imap_factory = imap_factory
        self._smtp_factory = smtp_factory

        self._poll_task: Optional[asyncio.Task] = None
        self._stopping = False

    @property
    def name(self) -> str:
        return "email"

    @property
    def platform_name(self) -> str:
        return "Email"

    # -----------------------------------------------------------------------
    # Inbound Email Processing
    # -----------------------------------------------------------------------

    async def handle_incoming_email(self, raw_bytes: bytes) -> Dict[str, Any]:
        """
        Parses and handles a single incoming email.
        Enforces security checks, validates pairing codes, dispatches queries to engine,
        and replies via SMTP with matching thread headers.
        """
        parsed = parse_email_message(raw_bytes)
        sender_email = parsed["from_email"]
        subject = parsed["subject"]
        message_id = parsed["message_id"]
        body = parsed["body"]

        if not sender_email:
            logger.warning("Ignored email with unparseable sender address.")
            return {"status": "ignored", "reason": "no_sender"}

        reply_subject = f"Re: {subject}" if not subject.lower().startswith("re:") else subject

        # Ingest into InboxManager for zero-cost priority classification & unified storage
        try:
            from makima.gateway.inbox import get_inbox_manager
            get_inbox_manager().ingest_message(
                platform="email",
                sender_id=sender_email,
                sender_name=parsed.get("from_name") or sender_email,
                subject=subject,
                content=body,
                message_id=message_id,
                metadata={"message_id": message_id, "from_raw": parsed.get("from_raw", "")},
            )
        except Exception as exc:
            logger.debug(f"Failed to ingest Email into InboxManager: {exc}")

        # 1. Pairing Code Check (Look for MK-XXXX pattern in subject or body)
        pairing_match = PAIRING_CODE_REGEX.search(subject) or PAIRING_CODE_REGEX.search(body)
        if pairing_match and not self.security_manager.is_allowed(sender_email):
            submitted_code = pairing_match.group(1).upper()
            is_valid = self.security_manager.verify_pairing_code("email", sender_email, submitted_code)

            if is_valid:
                reply_text = (
                    "✅ **Pairing Successful!**\n\n"
                    f"Your email address ({sender_email}) has been permanently authorized.\n"
                    "You can now send requests and instructions directly to Makima by replying to this email."
                )
                await self.send_message(
                    recipient_id=sender_email,
                    text=reply_text,
                    subject=reply_subject,
                    in_reply_to=message_id,
                )
                return {"status": "paired", "sender": sender_email}
            else:
                fail_text = (
                    "❌ **Pairing Failed**\n\n"
                    f"The pairing code '{submitted_code}' is invalid, already consumed, or expired.\n"
                    "Please request a fresh code on the Makima host console."
                )
                await self.send_message(
                    recipient_id=sender_email,
                    text=fail_text,
                    subject=reply_subject,
                    in_reply_to=message_id,
                )
                return {"status": "pairing_failed", "sender": sender_email}

        # 2. Security Allowlist Check
        if not self.security_manager.is_allowed(sender_email):
            unauth_text = (
                "🔒 **Authorization Required**\n\n"
                "This Makima assistant instance is private.\n"
                "To authorize your email address:\n"
                "1. Ask the host to generate a pairing code on the Makima console.\n"
                "2. Reply to this email with your code (e.g. Subject: MK-4921).\n\n"
                f"Your address: {sender_email}"
            )
            await self.send_message(
                recipient_id=sender_email,
                text=unauth_text,
                subject=reply_subject,
                in_reply_to=message_id,
            )
            return {"status": "unauthorized", "sender": sender_email}

        # 3. Authorized Query: Dispatch to HermesAgentEngine
        prompt = body or subject
        response_text = await self.process_user_query(
            user_id=sender_email,
            query=prompt,
            user_display_name=parsed["from_name"],
        )

        # 4. Reply via SMTP with Thread Continuity
        await self.send_message(
            recipient_id=sender_email,
            text=response_text,
            subject=reply_subject,
            in_reply_to=message_id,
        )

        return {
            "status": "success",
            "sender": sender_email,
            "subject": subject,
            "response_length": len(response_text),
        }

    # -----------------------------------------------------------------------
    # IMAP Polling Daemon
    # -----------------------------------------------------------------------

    def _get_imap_connection(self) -> Any:
        """Constructs an IMAP connection using configured credentials or mock factory."""
        if self._imap_factory:
            return self._imap_factory()

        if self.imap_ssl:
            client = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        else:
            client = imaplib.IMAP4(self.imap_host, self.imap_port)

        if self.username and self.password:
            client.login(self.username, self.password)

        return client

    async def check_unseen_emails(self, mark_seen: bool = True) -> List[Dict[str, Any]]:
        """
        Connects via IMAP, searches for UNSEEN messages, processes each.
        If mark_seen is False, uses non-destructive BODY.PEEK[] so messages stay unread in user's mail app.
        """
        results: List[Dict[str, Any]] = []

        def _fetch_sync():
            imap = self._get_imap_connection()
            try:
                imap.select("INBOX")
                status, search_data = imap.search(None, "UNSEEN")
                if status != "OK" or not search_data or not search_data[0]:
                    return []

                raw_emails = []
                msg_ids = search_data[0].split()
                fetch_cmd = "(RFC822)" if mark_seen else "(BODY.PEEK[])"
                for mid in msg_ids:
                    f_status, f_data = imap.fetch(mid, fetch_cmd)
                    if f_status == "OK" and f_data:
                        for part in f_data:
                            if isinstance(part, tuple) and len(part) >= 2:
                                raw_emails.append(part[1])
                                break
                    # Flag as seen only if requested
                    if mark_seen:
                        imap.store(mid, "+FLAGS", "\\Seen")

                return raw_emails
            finally:
                try:
                    imap.close()
                except Exception:
                    pass
                try:
                    imap.logout()
                except Exception:
                    pass

        try:
            raw_emails = await asyncio.to_thread(_fetch_sync)
            for raw_bytes in raw_emails:
                res = await self.handle_incoming_email(raw_bytes)
                if res:
                    results.append(res)
        except Exception as exc:
            logger.debug(f"IMAP poll error: {exc}")

        return results

    async def _poll_loop(self) -> None:
        """Continuous background task checking for new emails."""
        logger.info(f"Email adapter started polling every {self.poll_interval}s...")
        while not self._stopping:
            try:
                await self.check_unseen_emails()
            except Exception as e:
                logger.error(f"Error in EmailAdapter poll loop: {e}", exc_info=True)

            try:
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break

    # -----------------------------------------------------------------------
    # Outbound SMTP Delivery
    # -----------------------------------------------------------------------

    def _get_smtp_connection(self) -> Any:
        """Constructs an SMTP connection using configured settings or mock factory."""
        if self._smtp_factory:
            return self._smtp_factory()

        if self.smtp_ssl:
            client = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port)
        else:
            client = smtplib.SMTP(self.smtp_host, self.smtp_port)
            if self.smtp_starttls:
                context = ssl.create_default_context()
                client.starttls(context=context)

        if self.username and self.password:
            client.login(self.username, self.password)

        return client

    async def send_message(
        self,
        recipient_id: Union[str, int],
        text: str,
        subject: str = "Message from Makima",
        in_reply_to: Optional[str] = None,
    ) -> Any:
        """
        Sends an email message via SMTP.

        Args:
            recipient_id: Destination email address.
            text: Body text of the email.
            subject: Email Subject header.
            in_reply_to: Optional Message-ID of the parent email for threading.
        """
        to_email = str(recipient_id).strip()

        msg = EmailMessage()
        msg["From"] = self.from_address
        msg["To"] = to_email
        msg["Subject"] = subject
        msg["Date"] = email.utils.formatdate(localtime=True)
        msg["Message-ID"] = email.utils.make_msgid(domain="makima.local")

        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        msg.set_content(text)

        def _send_sync():
            smtp = self._get_smtp_connection()
            try:
                smtp.send_message(msg)
            finally:
                try:
                    smtp.quit()
                except Exception:
                    pass

        await asyncio.to_thread(_send_sync)
        logger.debug(f"Sent email to {to_email} with subject '{subject}'")
        return msg

    async def send_file(
        self,
        recipient_id: Union[str, int],
        file_path: Union[str, Path],
        caption: Optional[str] = None,
        subject: str = "File from Makima",
    ) -> Any:
        """Transmits an email with an attached file."""
        to_email = str(recipient_id).strip()
        p = Path(file_path).resolve()

        if not p.is_file():
            raise FileNotFoundError(f"File to attach does not exist: {file_path}")

        msg = MIMEMultipart()
        msg["From"] = self.from_address
        msg["To"] = to_email
        msg["Subject"] = subject
        msg["Date"] = email.utils.formatdate(localtime=True)
        msg["Message-ID"] = email.utils.make_msgid(domain="makima.local")

        # Body caption
        body_text = caption or f"Attached file: {p.name}"
        msg.attach(MIMEText(body_text, "plain", "utf-8"))

        # Attachment
        file_bytes = p.read_bytes()
        part = MIMEApplication(file_bytes, Name=p.name)
        part["Content-Disposition"] = f'attachment; filename="{p.name}"'
        msg.attach(part)

        def _send_sync():
            smtp = self._get_smtp_connection()
            try:
                smtp.send_message(msg)
            finally:
                try:
                    smtp.quit()
                except Exception:
                    pass

        await asyncio.to_thread(_send_sync)
        logger.info(f"Dispatched email with attachment '{p.name}' to {to_email}")
        return msg

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def start(self) -> None:
        """Starts background email polling daemon."""
        if self._is_connected:
            return

        self._stopping = False
        self._is_connected = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("Email adapter daemon started.")

    async def stop(self) -> None:
        """Halts email polling daemon."""
        self._stopping = True
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        self._is_connected = False
        logger.info("Email adapter daemon stopped.")

