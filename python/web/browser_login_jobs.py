"""Persistent one-time IndieGala browser-login jobs (PC helper → WebUI)."""

from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from paths import get_data_dir


@dataclass
class BrowserLoginJob:
    token: str
    account_id: str
    account_name: str
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    status: str = "pending"  # pending | complete | error | expired
    message: str = ""
    username: str = ""

    def to_public(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "account_id": self.account_id,
            "account_name": self.account_name,
            "status": self.status,
            "message": self.message,
            "username": self.username,
            "expires_in": max(0, int(self.expires_at - time.time())),
        }


class BrowserLoginStore:
    def __init__(self, ttl_seconds: int = 2700) -> None:
        # 45 minutes — login + Steam 2FA can take a while.
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._jobs: dict[str, BrowserLoginJob] = {}
        self._path = get_data_dir() / "browser_login_jobs.json"
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        jobs = raw.get("jobs") if isinstance(raw, dict) else None
        if not isinstance(jobs, list):
            return
        for item in jobs:
            if not isinstance(item, dict) or not item.get("token"):
                continue
            job = BrowserLoginJob(
                token=str(item["token"]),
                account_id=str(item.get("account_id") or ""),
                account_name=str(item.get("account_name") or ""),
                created_at=float(item.get("created_at") or time.time()),
                expires_at=float(item.get("expires_at") or 0),
                status=str(item.get("status") or "pending"),
                message=str(item.get("message") or ""),
                username=str(item.get("username") or ""),
            )
            self._jobs[job.token] = job

    def _save_locked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "jobs": [asdict(job) for job in self._jobs.values()],
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def _purge_locked(self) -> None:
        now = time.time()
        changed = False
        for token, job in list(self._jobs.items()):
            if job.status == "pending" and job.expires_at <= now:
                job.status = "expired"
                job.message = "Login link expired — start again."
                changed = True
            # Keep finished jobs briefly for UI polling; drop old junk.
            max_age = self._ttl * 2 if job.status == "pending" else 3600
            if now - job.created_at > max_age:
                self._jobs.pop(token, None)
                changed = True
        if changed:
            self._save_locked()

    def start(self, account_id: str, account_name: str) -> BrowserLoginJob:
        with self._lock:
            self._purge_locked()
            # Reuse existing pending token for this account (helper may still be running).
            for job in self._jobs.values():
                if (
                    job.account_id == account_id
                    and job.status == "pending"
                    and job.expires_at > time.time()
                ):
                    job.account_name = account_name or job.account_name
                    job.expires_at = time.time() + self._ttl
                    job.message = (
                        "Reuse existing login token — run the helper if not already."
                    )
                    self._save_locked()
                    return job

            token = secrets.token_urlsafe(24)
            job = BrowserLoginJob(
                token=token,
                account_id=account_id,
                account_name=account_name,
                expires_at=time.time() + self._ttl,
                message="Open the helper on your PC and log into IndieGala.",
            )
            self._jobs[token] = job
            self._save_locked()
            return job

    def get(self, token: str) -> Optional[BrowserLoginJob]:
        with self._lock:
            self._purge_locked()
            return self._jobs.get(token)

    def complete(
        self,
        token: str,
        *,
        ok: bool,
        message: str = "",
        username: str = "",
        allow_expired: bool = False,
    ) -> Optional[BrowserLoginJob]:
        with self._lock:
            self._purge_locked()
            job = self._jobs.get(token)
            if job is None:
                return None
            if job.status == "complete":
                return job
            if job.status == "pending" and time.time() > job.expires_at:
                if allow_expired:
                    # Cookie already captured — still accept within grace window.
                    pass
                else:
                    job.status = "expired"
                    job.message = "Login link expired — start again."
                    self._save_locked()
                    return job
            if job.status not in ("pending", "expired") and not (
                allow_expired and job.status == "expired"
            ):
                return job
            job.status = "complete" if ok else "error"
            job.message = message or ("Saved" if ok else "Failed")
            job.username = username
            self._save_locked()
            return job

    def claim_for_cookie_save(
        self,
        token: str,
        *,
        grace_seconds: int = 3600,
    ) -> Optional[BrowserLoginJob]:
        """
        Return job for saving a captured cookie.
        Accepts pending tokens, and recently expired ones (grace), because
        capture can finish after the UI token timer.
        """
        with self._lock:
            self._purge_locked()
            job = self._jobs.get(token)
            if job is None:
                return None
            if job.status == "complete":
                return job
            now = time.time()
            if job.status == "pending" and now <= job.expires_at:
                return job
            # Grace: expired/pending-overdue but still within created_at + grace
            if now <= job.created_at + grace_seconds:
                return job
            return None


browser_login_jobs = BrowserLoginStore()
