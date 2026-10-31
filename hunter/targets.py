"""What a candidate's config says about their targets: the home region, the job families, an optional priority
sector, and the angle (framing) each CV takes. The engine knows no person: a music priority, a Paris home or a set
of job families all come from candidates/<name>/config.yaml."""

DEFAULT_FRAMING = "Lead with the experience that proves the most for this posting."


def home_departments(cfg: dict) -> set[str]:
    """French departments of the home region ("75", "92"...): tier 1 with remote jobs, scored first."""
    return {str(d) for d in cfg.get("home_departments") or []}


def home_label(cfg: dict) -> str:
    """Short name of the home region for messages: "Paris", "Lyon"."""
    return cfg.get("home_label") or (cfg.get("home") or "home").split(",")[0].strip()


def priority(cfg: dict) -> dict:
    """The priority sector, if the candidate has one: its label, the family that gets a lower bar, the sector the
    scorer flags, the colors of its look. {} when there is none."""
    return cfg.get("priority") or {}


def is_priority(fit: dict, cfg: dict) -> bool:
    """A job in the priority sector, or in the priority family whatever the employer."""
    p = priority(cfg)
    return bool(p) and (bool(fit.get("priority_sector")) or bool(p.get("family")) and fit.get("family") == p["family"])


def priority_first(fit: dict, tier: int | None, cfg: dict) -> bool:
    """Priority jobs jump the queue, but only when they would also pass the normal bar: a weak role at a priority
    employer does not overtake a strong match elsewhere."""
    return is_priority(fit, cfg) and (fit.get("score") or 0) >= cfg["min_score"].get(tier or 2, 99)


def bar_for(fit: dict, cfg: dict) -> dict:
    """The lower priority bar is for roles of the priority family, not for any role at a priority employer."""
    p = priority(cfg)
    if p.get("min_score") and p.get("family") and fit.get("family") == p["family"]:
        return p["min_score"]
    return cfg["min_score"]


def default_framing(cfg: dict) -> str:
    return cfg.get("default_family") or "default"


def framing(fit: dict, cfg: dict) -> str:
    """The angle of the CV and letter: the priority family for any priority-sector job, else the job's family when
    the config has framing notes for it, else the default family."""
    p = priority(cfg)
    if p.get("family") and is_priority(fit, cfg):
        return p["family"]
    return fit.get("family") if fit.get("family") in (cfg.get("framing_notes") or {}) else default_framing(cfg)


def framing_note(cfg: dict, frame: str) -> str:
    notes = cfg.get("framing_notes") or {}
    return notes.get(frame) or notes.get(default_framing(cfg)) or DEFAULT_FRAMING
