"""Resource identities and contexts shared by collection, storage and validation."""

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def game_season(game_id: str) -> tuple[str, str]:
    year = 2000 + int(game_id[3:5])
    if year > datetime.now(timezone.utc).year + 1:
        year -= 100
    kinds = {
        "001": "Pre Season",
        "002": "Regular Season",
        "003": "All Star",
        "004": "Playoffs",
        "005": "PlayIn",
        "006": "Regular Season",
    }
    return f"{year}-{(year + 1) % 100:02d}", kinds.get(game_id[:3], "")


@dataclass
class GameContext:
    game_id: str
    team_ids: list[int] = field(default_factory=list)

    @property
    def season(self) -> tuple[str, str]:
        return game_season(self.game_id)


@dataclass(frozen=True)
class Resource:
    name: str
    module: str
    class_name: str
    root: str | None = None
    datasets: tuple[str, ...] = ()
    team_id: int | None = None
    group_id: str | None = None

    @property
    def source(self) -> str:
        return "nba_live_cdn" if self.module.startswith("live_") else "nba_stats"

    def bind(self, team_id: int, group_id: str | None = None) -> "Resource":
        return replace(self, team_id=team_id, group_id=group_id)

    def key(self, person_id: int | None = None) -> str:
        parts = [self.name]
        if person_id is not None:
            parts.append(str(person_id))
        if self.team_id is not None:
            parts.append(str(self.team_id))
        if self.group_id is not None:
            parts.append(self.group_id)
        return ":".join(parts)

    def relative_path(self, person_id: int | None = None) -> Path:
        if person_id is not None:
            return Path("raw/players") / f"{person_id}.json"
        root = Path("raw/live" if self.source == "nba_live_cdn" else "raw/stats")
        if self.team_id is not None:
            root /= self.name
            if self.group_id is not None:
                return root / str(self.team_id) / f"{self.group_id}.json"
            return root / f"{self.team_id}.json"
        return root / f"{self.name}.json"

    def request(self, game_id: str) -> Any:
        from nba_game.sources.stats import build_request

        return build_request(self, game_id)


@dataclass
class Response:
    raw: dict[str, Any]
    parameters: dict[str, Any]
    attempts: int
