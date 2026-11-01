"""What a candidate's config says about their targets: the country and home area, the contracts, the CV languages,
the job families, an optional priority sector, and the angle (framing) each CV takes. The engine knows no person
and no country: all of it comes from candidates/<name>/config.yaml."""
from . import geo
from .i18n import LABELS

DEFAULT_FRAMING = "Lead with the experience that proves the most for this posting."


def country(cfg: dict) -> str:
    """ISO code of the country the candidate searches in (FR, DE, US...). Every config sets it (Candidate refuses
    one without it, onboarding always writes it); FR only stands in for bare dicts in older stored data."""
    return str(cfg.get("country") or "FR").upper()


def home_city(cfg: dict) -> str:
    return (cfg.get("home") or "").split(",")[0].strip()


def home_departments(cfg: dict) -> set[str]:
    """France only, optional: departments of the home region ("75", "92"...), more precise than a radius."""
    return {str(d) for d in cfg.get("home_departments") or []}


def home_label(cfg: dict) -> str:
    """Short name of the home region for messages: "Paris", "Lyon"."""
    return cfg.get("home_label") or home_city(cfg) or "home"


def near_home(cfg: dict):
    """location -> True when the job is in the home area (cities within home_radius_km of home, or the home
    departments in France) or remote: tier 1, scored first."""
    deps = home_departments(cfg)
    area = geo.home_area(home_city(cfg), country(cfg), float(cfg.get("home_radius_km") or 40))

    def near(location: str) -> bool:
        if geo.REMOTE.search(geo.fold(location)):
            return True
        if deps:  # in France the department, when the location gives one, decides (Saint-Denis 93 vs 974)
            from .archive import department
            d = department(location)
            if d:
                return d in deps
        return geo.near(location, area)
    return near


# Contract types in every country's terms. Configs and older scores may use the French names.
CONTRACTS = {"cdi": "permanent", "cdd": "fixed_term", "permanent": "permanent", "fixed_term": "fixed_term",
             "freelance": "freelance", "interim": "interim", "internship_or_apprenticeship": "internship_or_apprenticeship",
             "internship": "internship_or_apprenticeship", "apprenticeship": "internship_or_apprenticeship",
             "unknown": "unknown"}
CONTRACT_LABELS = {"FR": {"permanent": "CDI", "fixed_term": "CDD"},
                   "": {"permanent": "Permanent", "fixed_term": "Fixed-term", "freelance": "Freelance"}}


def contract(value) -> str:
    return CONTRACTS.get(str(value or "").strip().lower(), "unknown")


def contract_ok(fit_contract, cfg: dict) -> bool:
    return contract(fit_contract) in {contract(c) for c in cfg.get("contracts") or ["permanent", "fixed_term", "unknown"]}


def contract_label(value, cfg: dict) -> str:
    """CDI / CDD in France, Permanent / Fixed-term elsewhere; '' when unknown."""
    labels = CONTRACT_LABELS.get(country(cfg), CONTRACT_LABELS[""])
    return labels.get(contract(value), "")


def cv_languages(cfg: dict) -> list[str]:
    """The languages the candidate's CVs can be written in: from the config, else English and the country's
    language. Postings in other languages get the first of these."""
    langs = cfg.get("cv_languages") or ["en", geo.country_language(country(cfg))]
    return [l for l in dict.fromkeys(str(x).lower() for x in langs) if l in LABELS] or ["en"]


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
