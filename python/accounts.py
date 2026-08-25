"""Platform-separated accounts (SteamGifts vs IndieGala) with optional proxy."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from paths import (
    get_accounts_file,
    get_cookie_file,
    get_indiegala_cookie_file,
)

PLATFORM_STEAMGIFTS = "steamgifts"
PLATFORM_INDIEGALA = "indiegala"
VALID_PLATFORMS = (PLATFORM_STEAMGIFTS, PLATFORM_INDIEGALA)


@dataclass
class Account:
    id: str
    name: str
    platform: str
    cookie: str = ""
    enabled: bool = True
    proxy: str = ""

    def to_public_dict(self, include_cookie: bool = False) -> dict[str, Any]:
        data = {
            "id": self.id,
            "name": self.name,
            "platform": self.platform,
            "enabled": self.enabled,
            "has_cookie": bool(self.cookie.strip()),
            "proxy": self.proxy,
        }
        if include_cookie:
            data["cookie"] = self.cookie
        return data


@dataclass
class AccountsState:
    active_steamgifts_id: str = ""
    active_indiegala_id: str = ""
    accounts: list[Account] = field(default_factory=list)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _normalize_platform(value: str) -> str:
    platform = (value or "").strip().lower()
    if platform not in VALID_PLATFORMS:
        raise ValueError("platform must be steamgifts or indiegala")
    return platform


def _migrate_legacy_cookies() -> AccountsState:
    accounts: list[Account] = []
    sg = ""
    ig = ""
    sg_path = get_cookie_file()
    ig_path = get_indiegala_cookie_file()
    if sg_path.exists():
        sg = sg_path.read_text(encoding="utf-8").strip()
    if ig_path.exists():
        ig = ig_path.read_text(encoding="utf-8").strip()

    sg_id = ""
    ig_id = ""
    if sg:
        sg_id = _new_id()
        accounts.append(
            Account(
                id=sg_id,
                name="SteamGifts 1",
                platform=PLATFORM_STEAMGIFTS,
                cookie=sg,
                enabled=True,
            )
        )
    if ig:
        ig_id = _new_id()
        accounts.append(
            Account(
                id=ig_id,
                name="IndieGala 1",
                platform=PLATFORM_INDIEGALA,
                cookie=ig,
                enabled=True,
            )
        )
    if not accounts:
        sg_id = _new_id()
        accounts.append(
            Account(
                id=sg_id,
                name="SteamGifts 1",
                platform=PLATFORM_STEAMGIFTS,
                enabled=True,
            )
        )
    return AccountsState(
        active_steamgifts_id=sg_id,
        active_indiegala_id=ig_id,
        accounts=accounts,
    )


def _migrate_combined_accounts(data: dict[str, Any]) -> AccountsState:
    """Split old combined accounts (both cookies on one row) into platform rows."""
    accounts: list[Account] = []
    for item in data.get("accounts") or []:
        if not isinstance(item, dict):
            continue

        # Already platform-separated.
        if item.get("platform") in VALID_PLATFORMS:
            accounts.append(
                Account(
                    id=str(item.get("id") or _new_id()),
                    name=str(item.get("name") or "Account"),
                    platform=str(item["platform"]),
                    cookie=str(item.get("cookie") or "").strip(),
                    enabled=bool(item.get("enabled", True)),
                    proxy=str(item.get("proxy") or "").strip(),
                )
            )
            continue

        sg_cookie = str(item.get("steamgifts_cookie") or "").strip()
        ig_cookie = str(item.get("indiegala_cookie") or "").strip()
        proxy = str(item.get("proxy") or "").strip()
        base_name = str(item.get("name") or "Account").strip() or "Account"
        enabled = bool(item.get("enabled", True))

        if sg_cookie or not ig_cookie:
            accounts.append(
                Account(
                    id=_new_id(),
                    name=f"{base_name} · SG" if ig_cookie else base_name,
                    platform=PLATFORM_STEAMGIFTS,
                    cookie=sg_cookie,
                    enabled=enabled,
                    proxy=proxy,
                )
            )
        if ig_cookie or bool(item.get("enable_indiegala")):
            accounts.append(
                Account(
                    id=_new_id(),
                    name=f"{base_name} · IG" if sg_cookie else base_name,
                    platform=PLATFORM_INDIEGALA,
                    cookie=ig_cookie,
                    enabled=enabled and (bool(ig_cookie) or bool(item.get("enable_indiegala"))),
                    proxy=proxy,
                )
            )

    if not accounts:
        return _migrate_legacy_cookies()

    sg_ids = [a.id for a in accounts if a.platform == PLATFORM_STEAMGIFTS]
    ig_ids = [a.id for a in accounts if a.platform == PLATFORM_INDIEGALA]
    return AccountsState(
        active_steamgifts_id=sg_ids[0] if sg_ids else "",
        active_indiegala_id=ig_ids[0] if ig_ids else "",
        accounts=accounts,
    )


def load_accounts() -> AccountsState:
    path = get_accounts_file()
    if not path.exists():
        state = _migrate_legacy_cookies()
        save_accounts(state)
        return state

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        state = _migrate_legacy_cookies()
        save_accounts(state)
        return state

    raw_accounts = data.get("accounts") or []
    needs_split = any(
        isinstance(item, dict)
        and item.get("platform") not in VALID_PLATFORMS
        for item in raw_accounts
    )
    if needs_split or not raw_accounts:
        state = _migrate_combined_accounts(data) if raw_accounts else _migrate_legacy_cookies()
        save_accounts(state)
        return state

    accounts: list[Account] = []
    for item in raw_accounts:
        if not isinstance(item, dict):
            continue
        try:
            platform = _normalize_platform(str(item.get("platform") or ""))
        except ValueError:
            continue
        accounts.append(
            Account(
                id=str(item.get("id") or _new_id()),
                name=str(item.get("name") or "Account"),
                platform=platform,
                cookie=str(item.get("cookie") or "").strip(),
                enabled=bool(item.get("enabled", True)),
                proxy=str(item.get("proxy") or "").strip(),
            )
        )

    if not accounts:
        state = _migrate_legacy_cookies()
        save_accounts(state)
        return state

    sg_ids = {a.id for a in accounts if a.platform == PLATFORM_STEAMGIFTS}
    ig_ids = {a.id for a in accounts if a.platform == PLATFORM_INDIEGALA}
    active_sg = str(data.get("active_steamgifts_id") or data.get("active_id") or "")
    active_ig = str(data.get("active_indiegala_id") or "")
    if active_sg not in sg_ids:
        active_sg = next(iter(sg_ids), "")
    if active_ig not in ig_ids:
        active_ig = next(iter(ig_ids), "")

    return AccountsState(
        active_steamgifts_id=active_sg,
        active_indiegala_id=active_ig,
        accounts=accounts,
    )


def save_accounts(state: AccountsState) -> None:
    path = get_accounts_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "active_steamgifts_id": state.active_steamgifts_id,
        "active_indiegala_id": state.active_indiegala_id,
        "accounts": [asdict(account) for account in state.accounts],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    cookie_path = get_cookie_file()
    ig_path = get_indiegala_cookie_file()
    cookie_path.parent.mkdir(parents=True, exist_ok=True)

    sg = get_active_account(PLATFORM_STEAMGIFTS, state)
    ig = get_active_account(PLATFORM_INDIEGALA, state)
    if sg and sg.cookie.strip():
        cookie_path.write_text(sg.cookie.strip(), encoding="utf-8")
    if ig and ig.cookie.strip():
        ig_path.write_text(ig.cookie.strip(), encoding="utf-8")


def get_active_account(
    platform: str,
    state: Optional[AccountsState] = None,
) -> Optional[Account]:
    state = state or load_accounts()
    platform = _normalize_platform(platform)
    active_id = (
        state.active_steamgifts_id
        if platform == PLATFORM_STEAMGIFTS
        else state.active_indiegala_id
    )
    for account in state.accounts:
        if account.id == active_id and account.platform == platform:
            return account
    for account in state.accounts:
        if account.platform == platform:
            return account
    return None


def enabled_accounts(
    platform: Optional[str] = None,
    state: Optional[AccountsState] = None,
) -> list[Account]:
    state = state or load_accounts()
    items = [a for a in state.accounts if a.enabled]
    if platform:
        platform = _normalize_platform(platform)
        items = [a for a in items if a.platform == platform]
    return items


def upsert_account(payload: dict[str, Any]) -> AccountsState:
    state = load_accounts()
    account_id = str(payload.get("id") or "").strip() or _new_id()
    existing = next((a for a in state.accounts if a.id == account_id), None)

    if existing is None:
        platform = _normalize_platform(str(payload.get("platform") or PLATFORM_STEAMGIFTS))
        name = str(payload.get("name") or "").strip()
        if not name:
            name = "SteamGifts" if platform == PLATFORM_STEAMGIFTS else "IndieGala"
        account = Account(id=account_id, name=name, platform=platform)
        state.accounts.append(account)
    else:
        account = existing
        if "name" in payload and str(payload.get("name") or "").strip():
            account.name = str(payload.get("name")).strip()
        # Platform is immutable after create.
        if "platform" in payload:
            requested = _normalize_platform(str(payload.get("platform") or ""))
            if requested != account.platform:
                raise ValueError("Cannot change account platform. Add a new account instead.")

    if "enabled" in payload:
        account.enabled = bool(payload["enabled"])
    if "cookie" in payload:
        # Never wipe a stored cookie with an empty field — switching accounts
        # in the UI often leaves the textarea blank briefly.
        new_cookie = str(payload.get("cookie") or "").strip()
        if new_cookie:
            account.cookie = new_cookie
        elif bool(payload.get("clear_cookie")):
            account.cookie = ""
    if "proxy" in payload:
        account.proxy = str(payload.get("proxy") or "").strip()

    if account.platform == PLATFORM_STEAMGIFTS and not state.active_steamgifts_id:
        state.active_steamgifts_id = account.id
    if account.platform == PLATFORM_INDIEGALA and not state.active_indiegala_id:
        state.active_indiegala_id = account.id

    save_accounts(state)
    return state


def delete_account(account_id: str) -> AccountsState:
    state = load_accounts()
    victim = next((a for a in state.accounts if a.id == account_id), None)
    state.accounts = [a for a in state.accounts if a.id != account_id]
    if not state.accounts:
        state = _migrate_legacy_cookies()
        save_accounts(state)
        return state

    if victim and victim.platform == PLATFORM_STEAMGIFTS:
        if state.active_steamgifts_id == account_id:
            state.active_steamgifts_id = next(
                (a.id for a in state.accounts if a.platform == PLATFORM_STEAMGIFTS),
                "",
            )
    if victim and victim.platform == PLATFORM_INDIEGALA:
        if state.active_indiegala_id == account_id:
            state.active_indiegala_id = next(
                (a.id for a in state.accounts if a.platform == PLATFORM_INDIEGALA),
                "",
            )
    save_accounts(state)
    return state


def set_active_account(account_id: str) -> AccountsState:
    state = load_accounts()
    account = next((a for a in state.accounts if a.id == account_id), None)
    if account is None:
        raise ValueError("Account not found.")
    if account.platform == PLATFORM_STEAMGIFTS:
        state.active_steamgifts_id = account_id
    else:
        state.active_indiegala_id = account_id
    save_accounts(state)
    return state


def public_accounts_payload(
    state: Optional[AccountsState] = None,
    include_cookies: bool = False,
) -> dict[str, Any]:
    state = state or load_accounts()
    return {
        "active_steamgifts_id": state.active_steamgifts_id,
        "active_indiegala_id": state.active_indiegala_id,
        "accounts": [
            a.to_public_dict(include_cookie=include_cookies) for a in state.accounts
        ],
    }


def get_account(account_id: str) -> Optional[Account]:
    state = load_accounts()
    return next((a for a in state.accounts if a.id == account_id), None)


def prune_empty_accounts() -> AccountsState:
    """Drop empty-cookie duplicates; keep one empty shell per platform if needed."""
    state = load_accounts()
    kept: list[Account] = []
    for platform in VALID_PLATFORMS:
        group = [a for a in state.accounts if a.platform == platform]
        with_cookie = [a for a in group if a.cookie.strip()]
        if with_cookie:
            kept.extend(with_cookie)
            continue
        if group:
            kept.append(group[0])

    state.accounts = kept
    sg_ids = [a.id for a in kept if a.platform == PLATFORM_STEAMGIFTS]
    ig_ids = [a.id for a in kept if a.platform == PLATFORM_INDIEGALA]
    if state.active_steamgifts_id not in sg_ids:
        state.active_steamgifts_id = sg_ids[0] if sg_ids else ""
    if state.active_indiegala_id not in ig_ids:
        state.active_indiegala_id = ig_ids[0] if ig_ids else ""
    if not kept:
        state = _migrate_legacy_cookies()
    save_accounts(state)
    return state
