"""A candidate is one person: profile, search settings, logos, database and output folder.
Add a person with `python -m hunter onboard <name> --cv cv.pdf`, or by copying candidates/example.

Two roots: the engine (this package, templates/, assets/, the fictional example) lives in ROOT; the data
(candidates/, data/, output/, .env) lives in HUNTER_HOME when that variable is set, else in ROOT as well."""
import os
import re
import unicodedata
from pathlib import Path

import yaml

from . import brand, web

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.getenv("HUNTER_HOME") or ROOT).resolve()
CANDIDATES = HOME / "candidates"
EXAMPLE = ROOT / "candidates" / "example"  # ships with the engine: the format onboarding follows, the tests' person
RESERVED = {"example", "jobs"}  # the engine's own person; data/jobs.db is the archive


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
    if not CANDIDATES.is_dir():
        return []
    return sorted(p.name for p in CANDIDATES.iterdir()
                  if (p / "profile.yaml").exists() and not p.name.startswith("_"))


def _int_keys(bars) -> dict:
    """{1: 55, 2: 65} whether the YAML wrote the tiers as numbers or as strings."""
    out = {}
    for k, v in (bars or {}).items():
        try:
            out[int(k)] = int(v)
        except (TypeError, ValueError):
            out[k] = v
    return out


def tidy(cfg: dict) -> dict:
    """Small repairs that keep a hand-written config from crashing a cycle."""
    if "min_score" in cfg:
        cfg["min_score"] = _int_keys(cfg["min_score"])
    if isinstance(cfg.get("priority"), dict) and cfg["priority"].get("min_score"):
        cfg["priority"]["min_score"] = _int_keys(cfg["priority"]["min_score"])
    return cfg


class Candidate:
    def __init__(self, who: str | None = None):
        names = available()
        people = [n for n in names if n != "example"]  # the example only counts when it is the only one
        who = who or os.getenv("HUNTER_CANDIDATE") or (people[0] if len(people) == 1 else names[0] if len(names) == 1 else "")
        if who not in names:
            hint = ", ".join(names) or "none yet: python -m hunter onboard <name> --cv cv.pdf"
            raise SystemExit(f"Choose a candidate with --who ({hint})")
        self.name = who
        self.dir = CANDIDATES / who
        self.profile_raw = (self.dir / "profile.yaml").read_text(encoding="utf-8")
        self.profile = yaml.safe_load(self.profile_raw)
        self.config = tidy(merge(load_yaml(ROOT / "config.yaml"), load_yaml(self.dir / "config.yaml")))
        if not self.config.get("country"):
            raise SystemExit(f"candidates/{who}/config.yaml needs `country: <ISO code>` (FR, DE, US...); "
                             "see docs/configuration.md")
        web.configure(self.config)
        brand.configure(self.config)
        self.out = Path(os.getenv("HUNTER_OUTPUT") or HOME / "output") / who
        self.db_path = HOME / "data" / f"{who}.db"

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
