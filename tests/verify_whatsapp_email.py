"""
Live verification script for Phase 2 Step 14: WhatsApp Web & Email Adapters.
Comprehensive testing covering:
  1. Email MIME parsing (single-part and multipart bodies, From headers, Message-ID).
  2. Email security interception: rejection of unauthorized emails.
  3. Email pairing code flow (MK-XXXX in Subject/Body, invalid code rejection, valid code authorization).
  4. Authorized email query execution via HermesAgentEngine with In-Reply-To/References thread headers.
  5. Mock IMAP unseen polling and mock SMTP delivery.
  6. Outbound email attachments via send_file().
  7. WhatsApp JID / phone normalization.
  8. WhatsApp security interception and pairing code flow (!pair <CODE> / MK-XXXX).
  9. WhatsApp authorized query execution via HermesAgentEngine.
  10. WhatsApp HTTP bridge dispatch for send_message and send_file (base64 payload).
"""

import asyncio
import email.message
import email.utils
import sys
import tempfile
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.core.engine import EngineResult
from makima.gateway.adapters import (
    EmailAdapter,
    WhatsAppAdapter,
    normalize_whatsapp_jid,
    parse_email_message,
)
from makima.gateway.security import GatewaySecurityManager


# ---------------------------------------------------------------------------
# Mock Helpers
# ---------------------------------------------------------------------------

class MockEngine:
    """Mock HermesAgentEngine that records calls and returns deterministic answers."""
    def __init__(self, reply_content: str = "Mocked engine response from Makima"):
        self.reply_content = reply_content
        self.call_history: List[Dict[str, Any]] = []

    async def run(self, prompt: str = "", **kwargs) -> EngineResult:
        self.call_history.append({"prompt": prompt, "kwargs": kwargs})
        return EngineResult(
            content=self.reply_content,
            messages=[],
            turn_count=1,
            tool_calls_executed=0,
            completed=True,
            model_used="mock-model",
        )


def build_raw_email(
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
    message_id: Optional[str] = None,
    is_multipart: bool = False,
) -> bytes:
    """Constructs raw RFC822 bytes for testing."""
    if is_multipart:
        msg = MIMEMultipart()
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg["Message-ID"] = message_id or email.utils.make_msgid()
        msg.attach(MIMEText(body, "plain", "utf-8"))
        # Add a dummy attachment
        attachment = MIMEApplication(b"dummy data", Name="dummy.txt")
        attachment["Content-Disposition"] = 'attachment; filename="dummy.txt"'
        msg.attach(attachment)
        return msg.as_bytes()
    else:
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg["Message-ID"] = message_id or email.utils.make_msgid()
        return msg.as_bytes()


# ---------------------------------------------------------------------------
# Test 1: Email Parsing & Header Extraction
# ---------------------------------------------------------------------------

def test_email_parsing():
    print("\n[TEST 1] Testing Email RFC822 parsing and header extraction...")

    raw_single = build_raw_email(
        from_addr="Alice Smith <alice@example.com>",
        to_addr="makima@example.com",
        subject="Project Alpha Status",
        body="Please provide an update on Project Alpha.",
        message_id="<msg-001@example.com>",
        is_multipart=False,
    )

    parsed_single = parse_email_message(raw_single)
    assert parsed_single["from_name"] == "Alice Smith"
    assert parsed_single["from_email"] == "alice@example.com"
    assert parsed_single["subject"] == "Project Alpha Status"
    assert parsed_single["message_id"] == "<msg-001@example.com>"
    assert "Please provide an update" in parsed_single["body"]

    # Multipart message
    raw_multi = build_raw_email(
        from_addr="bob@example.com",
        to_addr="makima@example.com",
        subject="Report with attachment",
        body="Here is the report body.",
        is_multipart=True,
    )
    parsed_multi = parse_email_message(raw_multi)
    assert parsed_multi["from_email"] == "bob@example.com"
    assert parsed_multi["body"] == "Here is the report body."

    print("  [PASS] Single-part and multipart emails parsed cleanly.")


# ---------------------------------------------------------------------------
# Test 2: Email Security Interception & Pairing Flow
# ---------------------------------------------------------------------------

async def test_email_security_and_pairing(tmp_dir: Path):
    print("\n[TEST 2] Testing Email adapter security interception and pairing flow...")

    sec_mgr = GatewaySecurityManager(
        allow_all_users=False,
        allowlist_user_ids=[],
        pairing_code_enabled=True,
        storage_path=tmp_dir / "email_users.json",
    )
    engine = MockEngine(reply_content="Autonomous response for Email.")
    adapter = EmailAdapter(
        username="makima@test.com",
        password="password",
        security_manager=sec_mgr,
        engine=engine,
    )

    # Intercept outbound send_message
    sent_emails = []

    async def mock_send_message(recipient_id, text, subject="Message", in_reply_to=None):
        sent_emails.append({
            "recipient": recipient_id,
            "text": text,
            "subject": subject,
            "in_reply_to": in_reply_to,
        })

    adapter.send_message = mock_send_message

    unauth_sender = "stranger@unknown.org"

    # 1. Unauthorized email without pairing code -> Access Denied reply
    unauth_email = build_raw_email(
        from_addr=f"Stranger <{unauth_sender}>",
        to_addr="makima@test.com",
        subject="Can I use your bot?",
        body="Hello I want access.",
        message_id="<req-01@unknown.org>",
    )
    res1 = await adapter.handle_incoming_email(unauth_email)
    assert res1["status"] == "unauthorized"
    assert len(sent_emails) == 1
    assert "Authorization Required" in sent_emails[0]["text"]
    assert sent_emails[0]["in_reply_to"] == "<req-01@unknown.org>"
    assert len(engine.call_history) == 0, "Engine must NOT be called for unauthorized user!"

    # 2. Invalid pairing code submitted in subject -> Pairing Failed
    invalid_email = build_raw_email(
        from_addr=unauth_sender,
        to_addr="makima@test.com",
        subject="Re: MK-0000",
        body="Here is my code: MK-0000",
        message_id="<req-02@unknown.org>",
    )
    res2 = await adapter.handle_incoming_email(invalid_email)
    assert res2["status"] == "pairing_failed"
    assert len(sent_emails) == 2
    assert "Pairing Failed" in sent_emails[1]["text"]
    assert not sec_mgr.is_allowed(unauth_sender)

    # 3. Valid pairing code submitted in body -> Pairing Successful
    code = sec_mgr.generate_pairing_code()
    valid_pair_email = build_raw_email(
        from_addr=unauth_sender,
        to_addr="makima@test.com",
        subject="Pairing Request",
        body=f"Hello, please pair my account with {code}.",
        message_id="<req-03@unknown.org>",
    )
    res3 = await adapter.handle_incoming_email(valid_pair_email)
    assert res3["status"] == "paired"
    assert len(sent_emails) == 3
    assert "Pairing Successful" in sent_emails[2]["text"]
    assert sec_mgr.is_allowed(unauth_sender)

    # 4. Subsequent email from now-authorized user -> Dispatches to HermesAgentEngine
    auth_email = build_raw_email(
        from_addr=unauth_sender,
        to_addr="makima@test.com",
        subject="Quarterly Analysis",
        body="Please prepare the quarterly performance review.",
        message_id="<task-01@unknown.org>",
    )
    res4 = await adapter.handle_incoming_email(auth_email)
    assert res4["status"] == "success"
    assert len(engine.call_history) == 1
    assert "quarterly performance review" in engine.call_history[0]["prompt"]
    assert len(sent_emails) == 4
    assert "Autonomous response for Email" in sent_emails[3]["text"]
    assert sent_emails[3]["in_reply_to"] == "<task-01@unknown.org>"
    assert sent_emails[3]["subject"] == "Re: Quarterly Analysis"

    print("  [PASS] Email security authorization, pairing code validation, and thread continuity verified.")


# ---------------------------------------------------------------------------
# Test 3: Mock IMAP Polling & Outbound Attachments
# ---------------------------------------------------------------------------

async def test_mock_imap_and_smtp(tmp_dir: Path):
    print("\n[TEST 3] Testing Mock IMAP polling daemon and SMTP outbound attachments...")

    sec_mgr = GatewaySecurityManager(
        allow_all_users=True,  # Open for this test
        storage_path=tmp_dir / "imap_users.json",
    )
    engine = MockEngine(reply_content="Processed via IMAP poll!")

    # Prepare raw email payload
    sample_email = build_raw_email(
        from_addr="reporter@daily.com",
        to_addr="makima@test.com",
        subject="Automated Report Query",
        body="Run system diagnostics now.",
        message_id="<diag-99@daily.com>",
    )

    # Mock IMAP Client
    mock_imap = MagicMock()
    mock_imap.select.return_value = ("OK", [b"1"])
    mock_imap.search.return_value = ("OK", [b"101"])
    mock_imap.fetch.return_value = ("OK", [(b"101 (RFC822 {100}", sample_email), b")"])

    # Mock SMTP Client
    mock_smtp = MagicMock()
    mock_smtp.send_message = MagicMock()

    adapter = EmailAdapter(
        username="makima@test.com",
        password="password",
        security_manager=sec_mgr,
        engine=engine,
        imap_factory=lambda: mock_imap,
        smtp_factory=lambda: mock_smtp,
    )

    # 1. Trigger IMAP poll
    results = await adapter.check_unseen_emails()
    assert len(results) == 1
    assert results[0]["status"] == "success"
    assert mock_imap.search.called
    assert mock_imap.fetch.called
    assert mock_smtp.send_message.called

    # 2. Test send_file attachment
    sample_file = tmp_dir / "budget.xlsx"
    sample_file.write_bytes(b"PK\x03\x04mock excel bytes")

    sent_msg = await adapter.send_file(
        recipient_id="cfo@company.com",
        file_path=sample_file,
        caption="Q1 Budget Forecast",
        subject="Fiscal Plan 2026",
    )
    assert sent_msg["Subject"] == "Fiscal Plan 2026"
    assert sent_msg["To"] == "cfo@company.com"
    assert mock_smtp.send_message.called

    print("  [PASS] Mock IMAP fetch and SMTP document attachment delivery verified.")


# ---------------------------------------------------------------------------
# Test 4: WhatsApp JID Normalization & Security Pairing
# ---------------------------------------------------------------------------

async def test_whatsapp_security_and_pairing(tmp_dir: Path):
    print("\n[TEST 4] Testing WhatsApp normalization, security, and pairing flow...")

    # JID Normalization
    assert normalize_whatsapp_jid("+1 (555) 234-5678") == "15552345678"
    assert normalize_whatsapp_jid("447123456789@s.whatsapp.net") == "447123456789"
    assert normalize_whatsapp_jid("919876543210@c.us") == "919876543210"

    sec_mgr = GatewaySecurityManager(
        allow_all_users=False,
        allowlist_user_ids=[],
        pairing_code_enabled=True,
        storage_path=tmp_dir / "wa_users.json",
    )
    engine = MockEngine(reply_content="Autonomous response from Makima for WhatsApp!")
    adapter = WhatsAppAdapter(
        security_manager=sec_mgr,
        engine=engine,
    )

    test_phone = "15550001111"

    # 1. Unauthorized message -> Access Denied
    unauth_payload = {
        "from": f"{test_phone}@s.whatsapp.net",
        "text": "Hello Makima!",
        "pushName": "John Doe",
    }
    res1 = await adapter.handle_incoming_message(unauth_payload)
    assert res1["status"] == "unauthorized"
    assert len(engine.call_history) == 0

    # 2. Invalid pairing code -> Failure
    invalid_pair_payload = {
        "from": test_phone,
        "text": "!pair MK-FAIL",
    }
    res2 = await adapter.handle_incoming_message(invalid_pair_payload)
    assert res2["status"] == "pairing_failed"
    assert not sec_mgr.is_user_authorized("whatsapp", test_phone)

    # 3. Valid pairing code -> Authorized
    code = sec_mgr.generate_pairing_code()
    valid_pair_payload = {
        "from": test_phone,
        "text": f"!pair {code}",
    }
    res3 = await adapter.handle_incoming_message(valid_pair_payload)
    assert res3["status"] == "paired"
    assert sec_mgr.is_user_authorized("whatsapp", test_phone)

    # 4. Authorized message -> Dispatches to HermesAgentEngine
    auth_payload = {
        "from": test_phone,
        "text": "Check deploy status on staging server",
    }
    res4 = await adapter.handle_incoming_message(auth_payload)
    assert res4["status"] == "success"
    assert len(engine.call_history) == 1
    assert "deploy status" in engine.call_history[0]["prompt"]
    assert "Autonomous response from Makima for WhatsApp!" in res4["response"]

    print("  [PASS] WhatsApp JID normalization, security pairing, and Hermes dispatching verified.")


# ---------------------------------------------------------------------------
# Test 5: WhatsApp HTTP Bridge Outbound Messaging & Media
# ---------------------------------------------------------------------------

async def test_whatsapp_bridge_dispatch(tmp_dir: Path):
    print("\n[TEST 5] Testing WhatsApp HTTP bridge outbound message and media dispatch...")

    # Mock HTTP client for WhatsApp Baileys bridge
    mock_http_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "wamid.001", "status": "sent"}
    mock_http_client.post.return_value = mock_resp

    adapter = WhatsAppAdapter(
        bridge_url="http://localhost:3000",
        api_key="secret-bridge-key",
        http_client=mock_http_client,
    )

    # 1. Send text message
    send_res = await adapter.send_message(
        recipient_id="+1 (555) 888-9999",
        text="Automated alert: High CPU utilization detected.",
    )
    assert send_res["status"] == "sent"
    assert send_res["recipient"] == "15558889999"
    assert mock_http_client.post.called

    # Check payload sent to bridge
    call_args = mock_http_client.post.call_args
    assert call_args[0][0] == "http://localhost:3000/send-message"
    sent_json = call_args[1]["json"]
    assert sent_json["to"] == "15558889999@s.whatsapp.net"
    assert "High CPU utilization" in sent_json["message"]

    # 2. Send media file
    doc_path = tmp_dir / "audit.pdf"
    doc_path.write_bytes(b"%PDF-1.4 mock pdf content")

    file_res = await adapter.send_file(
        recipient_id="15558889999",
        file_path=doc_path,
        caption="Security Audit Report",
    )
    assert file_res["status"] == "sent"
    assert file_res["filename"] == "audit.pdf"

    # Check media endpoint call
    media_call = mock_http_client.post.call_args
    assert media_call[0][0] == "http://localhost:3000/send-media"
    media_json = media_call[1]["json"]
    assert media_json["to"] == "15558889999@s.whatsapp.net"
    assert media_json["filename"] == "audit.pdf"
    assert len(media_json["data"]) > 0  # Base64 string

    print("  [PASS] WhatsApp bridge JSON/media outbound payloads verified.")


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------

async def main():
    print("=" * 75)
    print("MAKIMA v2 — STEP 14: WHATSAPP WEB & EMAIL ADAPTERS TEST SUITE")
    print("=" * 75)

    with tempfile.TemporaryDirectory() as temp_dir_str:
        tmp_dir = Path(temp_dir_str).resolve()
        test_email_parsing()
        await test_email_security_and_pairing(tmp_dir)
        await test_mock_imap_and_smtp(tmp_dir)
        await test_whatsapp_security_and_pairing(tmp_dir)
        await test_whatsapp_bridge_dispatch(tmp_dir)

    print("\n" + "=" * 75)
    print("ALL WHATSAPP & EMAIL ADAPTER TESTS PASSED (EXIT CODE 0)")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(main())
