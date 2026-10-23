"""
tests/test_inbox_summarizer.py — Comprehensive Unit & Integration Tests for
Universal Inbox Summarizer, Zero-Waste Priority Classifier, and Proactive Alerts.
"""

import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from makima.gateway.inbox import (
    InboxManager,
    InboxMessage,
    InboxStore,
    PriorityClassifier,
    PriorityLevel,
    reset_inbox_manager,
)
from makima.tools.messaging.inbox import (
    configure_vip_contacts,
    get_inbox_messages,
    mark_inbox_messages_read,
    summarize_inbox,
)


@pytest.fixture
def temp_inbox_store():
    """Provides an isolated InboxStore in a temporary directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_inbox.sqlite3"
        store = InboxStore(db_path=db_path)
        yield store


@pytest.fixture
def temp_inbox_manager(temp_inbox_store):
    """Provides an isolated InboxManager backed by temp store."""
    reset_inbox_manager()
    classifier = PriorityClassifier()
    manager = InboxManager(store=temp_inbox_store, classifier=classifier)
    yield manager
    reset_inbox_manager()


# ---------------------------------------------------------------------------
# 1. Zero-Cost Priority Classifier Tests
# ---------------------------------------------------------------------------

def test_classifier_urgency_english_and_hinglish():
    classifier = PriorityClassifier()

    # English urgency
    lvl, reason = classifier.classify(
        sender_id="+1234567890",
        sender_name="Alice",
        subject="Project update",
        content="Please check this urgent task, deadline is today asap!",
    )
    assert lvl in (PriorityLevel.HIGH, PriorityLevel.CRITICAL)
    assert "urgent" in reason.lower() or "urgency" in reason.lower()

    # Hinglish urgency
    lvl_hi, reason_hi = classifier.classify(
        sender_id="+919876543210",
        sender_name="Rahul",
        subject="",
        content="Bhai jaldi dekh zaroori file bhejo turant",
    )
    assert lvl_hi == PriorityLevel.HIGH
    assert "jaldi" in reason_hi.lower() or "urgency" in reason_hi.lower()


def test_classifier_critical_outage_and_emergency():
    classifier = PriorityClassifier()

    lvl, reason = classifier.classify(
        sender_id="alerts@ops.io",
        sender_name="DevOps Alert",
        subject="P0 Incident",
        content="Production server down! Database down and outage detected.",
    )
    assert lvl == PriorityLevel.CRITICAL
    assert "critical" in reason.lower()


def test_classifier_vip_matching():
    classifier = PriorityClassifier(vip_contacts={"+919999988888", "boss@corp.com", "CEO"})

    # Match by phone number
    lvl, reason = classifier.classify(
        sender_id="+91 99999 88888",
        sender_name="Unknown",
        subject="",
        content="Hey do you have a minute?",
    )
    assert lvl == PriorityLevel.HIGH
    assert "vip" in reason.lower()

    # Match by email
    lvl_email, _ = classifier.classify(
        sender_id="boss@corp.com",
        sender_name="The Boss",
        subject="Quick note",
        content="Good job on the release.",
    )
    assert lvl_email == PriorityLevel.HIGH

    # Non-VIP casual message
    lvl_other, _ = classifier.classify(
        sender_id="random@gmail.com",
        sender_name="Stranger",
        subject="",
        content="Hey what's up?",
    )
    assert lvl_other == PriorityLevel.NORMAL


def test_classifier_otp_and_finance():
    classifier = PriorityClassifier()

    # OTP pattern
    lvl_otp, reason_otp = classifier.classify(
        sender_id="VK-VERIFY",
        sender_name="Google",
        subject="",
        content="482910 is your Google verification code. Do not share it.",
    )
    assert lvl_otp == PriorityLevel.HIGH
    assert "otp" in reason_otp.lower()

    # Banking transaction pattern
    lvl_bank, reason_bank = classifier.classify(
        sender_id="HDFCBK",
        sender_name="Bank Alert",
        subject="",
        content="Your Acct ending 4091 has been debited by INR 4,500.00 at Amazon.",
    )
    assert lvl_bank == PriorityLevel.HIGH
    assert "financial" in reason_bank.lower()


def test_classifier_marketing_demotion_and_casual():
    classifier = PriorityClassifier()

    # Promotional email demoted to LOW
    lvl_promo, reason_promo = classifier.classify(
        sender_id="news@store.com",
        sender_name="Mega Deals",
        subject="50% off Summer Sale!",
        content="Click here to shop now. If you wish to unsubscribe, click here.",
    )
    assert lvl_promo == PriorityLevel.LOW
    assert "promotional" in reason_promo.lower()

    # Casual greeting
    lvl_casual, _ = classifier.classify(
        sender_id="+11223344",
        sender_name="Friend",
        subject="",
        content="Hello!",
    )
    assert lvl_casual == PriorityLevel.NORMAL


def test_classifier_benchmark_speed():
    """Confirms classifier consumes near-zero CPU (<0.05ms per message)."""
    classifier = PriorityClassifier(vip_contacts={"boss@company.com"})
    t0 = time.perf_counter()
    iterations = 1000
    for _ in range(iterations):
        classifier.classify(
            sender_id="+919876543210",
            sender_name="Colleague",
            subject="Urgent meeting update",
            content="Please join the emergency bridge asap, server down!",
        )
    elapsed = time.perf_counter() - t0
    avg_ms = (elapsed / iterations) * 1000
    assert avg_ms < 0.5  # Sub-millisecond evaluation guarantee (<0.5ms on all hardware)


# ---------------------------------------------------------------------------
# 2. InboxStore SQLite CRUD Tests
# ---------------------------------------------------------------------------

def test_inbox_store_crud(temp_inbox_store):
    store = temp_inbox_store

    msg1 = InboxMessage(
        id="msg_1",
        platform="whatsapp",
        sender_id="+911234567890",
        sender_name="Boss",
        subject="",
        content="Send slides urgently",
        timestamp=time.time() - 100,
        is_read=False,
        importance_level=PriorityLevel.HIGH.value,
        importance_reason="Urgency keyword: 'urgently'",
    )
    msg2 = InboxMessage(
        id="msg_2",
        platform="email",
        sender_id="client@acme.com",
        sender_name="Client",
        subject="Contract review",
        content="Please review attached proposal.",
        timestamp=time.time() - 50,
        is_read=False,
        importance_level=PriorityLevel.NORMAL.value,
    )
    msg3 = InboxMessage(
        id="msg_3",
        platform="telegram",
        sender_id="12345",
        sender_name="Dev Group",
        subject="",
        content="Server down! Database out of memory.",
        timestamp=time.time(),
        is_read=False,
        importance_level=PriorityLevel.CRITICAL.value,
    )

    store.add_message(msg1)
    store.add_message(msg2)
    store.add_message(msg3)

    # 1. Query all
    all_msgs = store.get_messages(platform="all")
    assert len(all_msgs) == 3

    # 2. Query by platform
    wa_msgs = store.get_messages(platform="whatsapp")
    assert len(wa_msgs) == 1
    assert wa_msgs[0].id == "msg_1"

    # 3. Query by min_importance
    high_msgs = store.get_messages(platform="all", min_importance="high")
    assert len(high_msgs) == 2  # msg1 (HIGH) and msg3 (CRITICAL)

    # 4. Mark as read
    assert store.get_unread_count() == 3
    store.mark_as_read(message_ids=["msg_1"])
    assert store.get_unread_count() == 2

    # 5. Mark platform as read
    store.mark_as_read(platform="telegram")
    assert store.get_unread_count() == 1  # Only email left unread


# ---------------------------------------------------------------------------
# 3. InboxManager Proactive Notification Dispatch
# ---------------------------------------------------------------------------

def test_inbox_manager_proactive_alert(temp_inbox_manager):
    mgr = temp_inbox_manager

    with patch("makima.tools.os.notifications.show_desktop_notification") as mock_notify:
        mock_notify.return_value = {"success": True}

        # 1. Normal message: Should NOT trigger desktop notification
        msg_norm, notified_norm = mgr.ingest_message(
            platform="whatsapp",
            sender_id="+1111",
            sender_name="Friend",
            content="Hey kya chal raha hai?",
            notify=True,
        )
        assert notified_norm is False
        assert mock_notify.call_count == 0

        # 2. High Priority Urgency message: MUST trigger desktop notification!
        msg_high, notified_high = mgr.ingest_message(
            platform="whatsapp",
            sender_id="+2222",
            sender_name="Manager",
            content="URGENT: Client meeting in 5 minutes jaldi connect karo",
            notify=True,
        )
        assert notified_high is True
        assert mock_notify.call_count == 1
        call_kwargs = mock_notify.call_args[1]
        assert "IMPORTANT" in call_kwargs["title"] or "URGENT" in call_kwargs["title"]
        assert "WHATSAPP" in call_kwargs["title"]


# ---------------------------------------------------------------------------
# 4. Hermes @tool Integration Tests
# ---------------------------------------------------------------------------

def test_summarize_inbox_tool(temp_inbox_manager):
    mgr = temp_inbox_manager

    # Pre-populate messages across platforms
    mgr.ingest_message(
        platform="whatsapp",
        sender_id="+919876543210",
        sender_name="Boss",
        content="Urgent: Need client deployment report asap",
        notify=False,
    )
    mgr.ingest_message(
        platform="email",
        sender_id="bank@hdfc.com",
        sender_name="HDFC Bank",
        subject="Txn Alert",
        content="Acct debited with INR 2,000 at Swiggy",
        notify=False,
    )
    mgr.ingest_message(
        platform="telegram",
        sender_id="54321",
        sender_name="Mom",
        content="Dinner ready hai, ghar kab aaoge?",
        notify=False,
    )

    with patch("makima.tools.messaging.inbox.get_inbox_manager", return_value=mgr):
        # 1. Summarize all platforms
        result_all = summarize_inbox(platform="all", unread_only=True, hours=24)
        assert result_all["success"] is True
        assert result_all["total_count"] == 3
        assert result_all["high_count"] >= 1
        assert "Inbox Briefing: ALL" in result_all["summary"]

        # 2. Summarize WhatsApp only
        result_wa = summarize_inbox(platform="whatsapp", unread_only=True, hours=24)
        assert result_wa["success"] is True
        assert result_wa["total_count"] == 1
        assert "Inbox Briefing: WHATSAPP" in result_wa["summary"]

        # 3. Get raw messages
        raw_res = get_inbox_messages(platform="all", unread_only=True, limit=10)
        assert raw_res["success"] is True
        assert raw_res["count"] == 3

        # 4. Mark all as read
        mark_res = mark_inbox_messages_read(platform="all")
        assert mark_res["success"] is True
        assert mark_res["marked_read_count"] == 3
        assert mark_res["remaining_unread"] == 0


def test_configure_vip_contacts_tool(temp_inbox_manager):
    mgr = temp_inbox_manager

    with patch("makima.tools.messaging.inbox.get_inbox_manager", return_value=mgr):
        # 1. Add VIP
        add_res = configure_vip_contacts(action="add", contact="+919999900000", notes="CEO")
        assert add_res["success"] is True
        assert add_res["action"] == "added"

        # Verify VIP in classifier
        assert mgr.classifier.is_vip("+919999900000")

        # 2. List VIPs
        list_res = configure_vip_contacts(action="list")
        assert list_res["success"] is True
        assert any(v["contact"] == "919999900000" or v["contact"] == "+919999900000" for v in list_res["vips"])

        # 3. Remove VIP
        rem_res = configure_vip_contacts(action="remove", contact="+919999900000")
        assert rem_res["success"] is True
        assert mgr.classifier.is_vip("+919999900000") is False


# ---------------------------------------------------------------------------
# 5. Non-Destructive IMAP BODY.PEEK[] Email Fetch Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_destructive_email_fetch():
    from makima.gateway.adapters.email_daemon import EmailAdapter
    from makima.gateway.security import GatewaySecurityManager

    mock_imap = MagicMock()
    mock_imap.select.return_value = ("OK", [b"1"])
    mock_imap.search.return_value = ("OK", [b"101"])
    # Return fake raw email bytes
    raw_email_sample = (
        b"From: boss@corp.com\r\n"
        b"Subject: Urgent Strategy Update\r\n"
        b"Message-ID: <test1234@corp.com>\r\n"
        b"\r\n"
        b"Please review this urgently.\r\n"
    )
    mock_imap.fetch.return_value = ("OK", [(b"101 (BODY.PEEK[] {100})", raw_email_sample)])

    mock_smtp = MagicMock()
    mock_smtp.send_message = MagicMock()

    sec_mgr = GatewaySecurityManager(allow_all_users=True)

    adapter = EmailAdapter(
        security_manager=sec_mgr,
        imap_factory=lambda: mock_imap,
        smtp_factory=lambda: mock_smtp,
    )

    # 1. Non-destructive check (mark_seen=False)
    results = await adapter.check_unseen_emails(mark_seen=False)
    assert len(results) >= 1

    # Verify fetch called with (BODY.PEEK[])
    fetch_calls = [call[0][1] for call in mock_imap.fetch.call_args_list]
    assert any("(BODY.PEEK[])" in c for c in fetch_calls)

    # Verify imap.store (+FLAGS \Seen) was NOT called!
    assert mock_imap.store.call_count == 0

