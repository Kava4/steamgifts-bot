import json
import time
from dataclasses import asdict, dataclass
from typing import Optional

from paths import get_data_dir
from steamgifts_service import EnteredGiveawayInfo, GiveawayInfo


@dataclass
class StoredEntered:
    code: str
    name: str
    cost: int
    image_url: str
    source: str
    url: str = ""
    ends_at: int = 0
    remaining_label: str = ""
    entered_at: float = 0.0

    def to_entered_info(self) -> EnteredGiveawayInfo:
        return EnteredGiveawayInfo(
            name=self.name,
            code=self.code,
            cost=self.cost,
            image_url=self.image_url,
            ends_at=self.ends_at,
            remaining_label=self.remaining_label or "",
            entries_count="",
            entered_label="IndieGala",
            xsrf_token="",
            source=self.source,
            url=self.url,
        )


def _entered_file(account_id: str = ""):
    data_dir = get_data_dir()
    if account_id:
        safe = "".join(ch for ch in account_id if ch.isalnum() or ch in ("-", "_"))
        if safe:
            return data_dir / f"indiegala_entered_{safe}.json"
    return data_dir / "indiegala_entered.json"


class IndieGalaEnteredTracker:
    def __init__(self, account_id: str = "") -> None:
        self.account_id = (account_id or "").strip()
        self._items: dict[str, StoredEntered] = {}
        self.load()

    def load(self) -> None:
        path = _entered_file(self.account_id)
        if not path.exists() and self.account_id:
            # Fall back to legacy shared file once.
            legacy = _entered_file("")
            path = legacy if legacy.exists() else path
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        items = data.get("items", [])
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict) or not item.get("code"):
                continue
            code = str(item["code"])
            self._items[code] = StoredEntered(
                code=code,
                name=str(item.get("name", "Unknown")),
                cost=int(item.get("cost", 0) or 0),
                image_url=str(item.get("image_url", "")),
                source="indiegala",
                url=str(item.get("url", "")),
                ends_at=int(item.get("ends_at", 0) or 0),
                remaining_label=str(item.get("remaining_label", "")),
                entered_at=float(item.get("entered_at", 0) or 0),
            )
        self._prune_expired(save=False)

    def save(self) -> None:
        path = _entered_file(self.account_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"items": [asdict(item) for item in self._items.values()]}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def add_from_giveaway(self, giveaway: GiveawayInfo) -> None:
        url = ""
        if giveaway.code:
            url = f"https://www.indiegala.com/giveaways/card/{giveaway.code}"
        self._items[giveaway.code] = StoredEntered(
            code=giveaway.code,
            name=giveaway.name,
            cost=giveaway.cost,
            image_url=giveaway.image_url,
            source="indiegala",
            url=url,
            ends_at=int(giveaway.ends_at or 0),
            remaining_label=giveaway.ends_label or "",
            entered_at=time.time(),
        )
        self.save()

    def merge_entered(self, items: list[EnteredGiveawayInfo]) -> int:
        """Upsert remote entered cards. Returns how many new codes were added."""
        added = 0
        now = time.time()
        for item in items:
            if not item.code:
                continue
            existing = self._items.get(item.code)
            if existing is None:
                added += 1
                entered_at = now
            else:
                entered_at = existing.entered_at or now
            self._items[item.code] = StoredEntered(
                code=item.code,
                name=item.name or (existing.name if existing else "Unknown"),
                cost=int(item.cost or (existing.cost if existing else 0) or 0),
                image_url=item.image_url
                or (existing.image_url if existing else ""),
                source="indiegala",
                url=item.url
                or (
                    existing.url
                    if existing
                    else f"https://www.indiegala.com/giveaways/card/{item.code}"
                ),
                ends_at=int(item.ends_at or (existing.ends_at if existing else 0) or 0),
                remaining_label=item.remaining_label
                or (existing.remaining_label if existing else ""),
                entered_at=entered_at,
            )
        if items:
            self.save()
        return added

    def list_active(self) -> list[EnteredGiveawayInfo]:
        self._prune_expired(save=True)
        items = sorted(
            self._items.values(),
            key=lambda item: item.entered_at,
            reverse=True,
        )
        return [item.to_entered_info() for item in items]

    def _prune_expired(self, save: bool) -> None:
        now = int(time.time())
        changed = False
        for code in list(self._items.keys()):
            ends_at = self._items[code].ends_at
            if ends_at and ends_at <= now:
                del self._items[code]
                changed = True
        if changed and save:
            self.save()
