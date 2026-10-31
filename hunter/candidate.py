"""A candidate is one person: profile, search settings, logos, database and output folder.
Add a person with `python -m hunter onboard <name> --cv cv.pdf`, or by copying candidates/example."""
import os
import re
import unicodedata
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES = ROOT / "candidates"


def file_part(name: str, limit: int = 40) -> str:
    """'Société Générale' -> 'Societe-Generale', for file names."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_name).strip("-")[:limit].strip("-")


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def available() -> list[str]:
    return sorted(p.name for p in CANDIDATES.iterdir()
                  if (p / "profile.yaml").exists() and not p.name.startswith("_"))


class Candidate:
    def __init__(self, who: str | None = None):
        names = available()
        who = who or os.getenv("HUNTER_CANDIDATE") or (names[0] if len(names) == 1 else "")
        if who not in names:
            raise SystemExit(f"Choose a candidate with --who ({', '.join(names)})")
        self.name = who
        self.dir = CANDIDATES / who
        self.profile_raw = (self.dir / "profile.yaml").read_text(encoding="utf-8")
        self.profile = yaml.safe_load(self.profile_raw)
        self.config = merge(load_yaml(ROOT / "config.yaml"), load_yaml(self.dir / "config.yaml"))
        self.out = Path(os.getenv("HUNTER_OUTPUT") or ROOT / "output") / who
        self.db_path = ROOT / "data" / f"{who}.db"

    @property
    def full_name(self) -> str:
        return self.profile["identity"]["name"]

    @property
    def file_stem(self) -> str:
        """'Alex Moreau' -> 'Alex-Moreau': hyphens, no accents, as recruiters' systems store it."""
        return file_part(self.full_name)

    def allowed_skills(self) -> set[str]:
        s = self.profile["skills"]
        return {x for group in s["confirmed"].values() for x in group} | set(s["implied"])

    def env(self, key: str) -> str:
        """Per-candidate value from .env (KEY_ALEX) with a shared fallback (KEY)."""
        return os.getenv(f"{key}_{self.name.upper()}") or os.getenv(key) or ""
