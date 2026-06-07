import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from paths import get_data_dir
from steamgifts_service import WonGiveawayInfo


@dataclass
class StoredWin:
    code: str
    name: str
    image_url: str
    source: str
    url: str
    detected_at: str = ""

    @classmethod
    def from_info(cls, info: WonGiveawayInfo) -> "StoredWin":
        return cls(
            code=info.code,
            name=info.name,
            image_url=info.image_url,
            source=info.source,
            url=info.url,
            detected_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_info(self) -> WonGiveawayInfo:
        return WonGiveawayInfo(
            name=self.name,
            code=self.code,
            image_url=self.image_url,
            source=self.source,
            url=self.url,
        )


def _wins_file():
    return get_data_dir() / "known_wins.json"


class WinsTracker:
    def __init__(self):
        self._wins: dict[str, dict[str, StoredWin]] = {
            "steamgifts": {},
            "indiegala": {},
        }
        self.baseline_done = False
        self.load()

    def load(self) -> None:
        path = _wins_file()
        if not path.exists():
            return

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        for source in ("steamgifts", "indiegala"):
            items = data.get(source, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict) or not item.get("code"):
                    continue
                stored = StoredWin(
                    code=str(item["code"]),
                    name=str(item.get("name", "Unknown")),
                    image_url=str(item.get("image_url", "")),
                    source=source,
                    url=str(item.get("url", "")),
                    detected_at=str(item.get("detected_at", "")),
                )
                self._wins[source][stored.code] = stored

        self.baseline_done = bool(data.get("baseline_done", False))

    def save(self) -> None:
        path = _wins_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "baseline_done": self.baseline_done,
            "steamgifts": [
                asdict(win) for win in self._wins["steamgifts"].values()
            ],
            "indiegala": [
                asdict(win) for win in self._wins["indiegala"].values()
            ],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def all_wins(self) -> list[StoredWin]:
        wins = list(self._wins["steamgifts"].values())
        wins.extend(self._wins["indiegala"].values())
        wins.sort(key=lambda item: item.detected_at or "", reverse=True)
        return wins

    def sync_wins(self, current: list[WonGiveawayInfo]) -> list[WonGiveawayInfo]:
        """Keep only unclaimed wins and return newly discovered ones to notify."""
        is_first = not self.baseline_done
        new_wins: list[WonGiveawayInfo] = []
        current_by_source: dict[str, dict[str, WonGiveawayInfo]] = {
            "steamgifts": {},
            "indiegala": {},
        }

        for info in current:
            source = info.source if info.source in self._wins else "steamgifts"
            current_by_source[source][info.code] = info

        for source in ("steamgifts", "indiegala"):
            current_codes = current_by_source[source]

            for code in list(self._wins[source].keys()):
                if code not in current_codes:
                    del self._wins[source][code]

            for code, info in current_codes.items():
                if code in self._wins[source]:
                    stored = self._wins[source][code]
                    if info.name:
                        stored.name = info.name
                    if info.image_url:
                        stored.image_url = info.image_url
                    if info.url:
                        stored.url = info.url
                    continue

                self._wins[source][code] = StoredWin.from_info(info)
                if not is_first:
                    new_wins.append(info)

        self.baseline_done = True
        self.save()
        return new_wins
