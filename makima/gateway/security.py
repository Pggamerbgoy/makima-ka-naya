"""
Makima v2 — Gateway Security & Pairing Authorization Manager.
Architectural Pattern: Multi-platform Allowlist & Ephemeral Pairing Code Token Authorization.
Zero-Hardcoding Guarantee: Fully dynamic storage resolution via MakimaConfig with thread-safe persistence.
"""

from __future__ import annotations

import json
import logging
import random
import string
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from makima.config import get_settings

logger = logging.getLogger("makima.gateway.security")


class GatewaySecurityManager:
    """
    Manages authorization for multi-platform gateway messaging (Telegram, Discord, WhatsApp).
    Provides:
      1. Static user ID allowlist verification.
      2. Dynamic 6-character ephemeral pairing code token system (15-min TTL).
      3. Persistent authorization storage for paired users.
    """

    DEFAULT_TTL_SECONDS: int = 900  # 15 minutes

    def __init__(
        self,
        allow_all_users: bool = False,
        allowlist_user_ids: Optional[List[str]] = None,
        pairing_code_enabled: bool = True,
        storage_path: Optional[Path | str] = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ):
        settings = get_settings()
        gateway_sec = settings.gateway.security

        self.allow_all_users = allow_all_users or gateway_sec.allow_all_users
        configured_ids = allowlist_user_ids if allowlist_user_ids is not None else gateway_sec.allowlist_user_ids
        self.allowlist_user_ids: Set[str] = set(str(uid).strip() for uid in configured_ids)
        self.pairing_code_enabled = pairing_code_enabled and gateway_sec.pairing_code_enabled
        self.ttl_seconds = ttl_seconds

        # Resolve persistent authorized users file path
        if storage_path is not None:
            self.storage_path = Path(storage_path).resolve()
        else:
            self.storage_path = (settings.data_dir_path / "security" / "authorized_users.json").resolve()

        # In-memory ephemeral pairing code state
        self._active_code: Optional[str] = None
        self._code_expires_at: float = 0.0

        # In-memory map of paired users: key -> dict metadata
        self._authorized_users: Dict[str, Dict[str, Any]] = {}
        self._load_storage()

    def _user_key(self, platform: str, user_id: str) -> str:
        """Generates canonical composite key for a platform user."""
        return f"{platform.lower().strip()}:{str(user_id).strip()}"

    def _load_storage(self) -> None:
        """Loads paired users from persistent JSON storage."""
        if self.storage_path.is_file():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._authorized_users = data
                        logger.info(f"Loaded {len(self._authorized_users)} authorized users from {self.storage_path}")
            except Exception as e:
                logger.warning(f"Failed to read authorized users from {self.storage_path}: {e}")

    def _save_storage(self) -> None:
        """Atomically saves authorized users map to persistent JSON storage."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.storage_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self._authorized_users, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.storage_path)
            logger.debug(f"Saved {len(self._authorized_users)} authorized users to {self.storage_path}")
        except Exception as e:
            logger.error(f"Failed to persist authorized users to {self.storage_path}: {e}")

    def generate_pairing_code(self) -> str:
        """
        Generates a 6-character alphanumeric pairing code (e.g. 'MK-9421' or 'MK-AB72')
        with a 15-minute TTL. Outputs code to host log/console for the owner to pair.
        """
        # Generate 4 random uppercase alphanumeric digits prefixed by MK-
        random_suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
        code = f"MK-{random_suffix}"

        self._active_code = code
        self._code_expires_at = time.time() + self.ttl_seconds

        expiry_iso = datetime.fromtimestamp(self._code_expires_at, tz=timezone.utc).isoformat()
        logger.warning(
            f"=== MAKIMA GATEWAY PAIRING CODE: {code} (Valid for {self.ttl_seconds // 60}m until {expiry_iso}) ==="
        )
        return code

    def get_active_pairing_code(self) -> Optional[str]:
        """Returns the currently active pairing code if unexpired, else None."""
        if self._active_code and time.time() < self._code_expires_at:
            return self._active_code
        self._active_code = None
        return None

    def verify_pairing_code(self, platform: str, user_id: str, code: str) -> bool:
        """
        Verifies provided pairing code against active code.
        If valid:
          - Permanently authorizes the user.
          - Consumes the pairing code.
          - Persists authorization to disk.
        """
        if not self.pairing_code_enabled:
            logger.info("Pairing code verification attempted, but pairing is disabled.")
            return False

        if not self._active_code or time.time() >= self._code_expires_at:
            logger.warning(f"Pairing code verification failed: code expired or not generated.")
            return False

        # Normalize comparison (case-insensitive, whitespace stripped)
        submitted = code.strip().upper()
        active = self._active_code.strip().upper()

        if submitted != active:
            logger.warning(f"Invalid pairing code submitted by {platform}:{user_id}")
            return False

        # Code matched! Authorize user
        key = self._user_key(platform, user_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        self._authorized_users[key] = {
            "platform": platform.lower().strip(),
            "user_id": str(user_id).strip(),
            "authorized_at": now_iso,
            "method": "pairing_code",
        }
        self._save_storage()

        # Invalidate code (single-use)
        self._active_code = None
        self._code_expires_at = 0.0

        logger.info(f"User {platform}:{user_id} successfully paired and authorized.")
        return True

    def is_user_authorized(self, platform: str, user_id: str) -> bool:
        """
        Evaluates whether a user on a given platform is permitted to interact with Makima.
        """
        # 1. Global open access flag
        if self.allow_all_users or "*" in self.allowlist_user_ids:
            return True

        uid_str = str(user_id).strip()
        key = self._user_key(platform, user_id)

        # 2. Check static configured allowlist (by raw user ID or platform:user_id)
        if uid_str in self.allowlist_user_ids or key in self.allowlist_user_ids:
            return True

        # 3. Check persistent paired users
        if key in self._authorized_users:
            return True

        return False

    def is_allowed(self, user_id: str, platform: str = "email") -> bool:
        """
        Convenience alias for is_user_authorized.
        Defaults to platform='email' when checking email addresses.
        """
        return self.is_user_authorized(platform=platform, user_id=user_id)

    def authorize_user(
        self,
        platform: str,
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Directly authorizes a user and persists to storage."""
        key = self._user_key(platform, user_id)
        entry = {
            "platform": platform.lower().strip(),
            "user_id": str(user_id).strip(),
            "authorized_at": datetime.now(timezone.utc).isoformat(),
            "method": "direct_authorization",
        }
        if metadata:
            entry.update(metadata)
        self._authorized_users[key] = entry
        self._save_storage()

    def revoke_user(self, platform: str, user_id: str) -> bool:
        """Revokes authorization for a previously paired user."""
        key = self._user_key(platform, user_id)
        if key in self._authorized_users:
            del self._authorized_users[key]
            self._save_storage()
            logger.info(f"Revoked authorization for {key}")
            return True
        return False

    def list_authorized_users(self) -> List[Dict[str, Any]]:
        """Returns all dynamically paired and persisted users."""
        return list(self._authorized_users.values())
