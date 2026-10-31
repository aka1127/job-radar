"""Open data: the State's file of every public-sector job offer (Choisir le Service Public: State, local government and
hospitals, about 280,000 offers a year), published on data.gouv.fr under the Licence Ouverte 2.0 and imported into the
national archive whenever a new version comes out."""
import csv
import logging
import re
from datetime import date, datetime, timedelta, timezone

import requests

from .candidate import ROOT

log = logging.getLogger(__name__)
DATASET = "https://www.data.gouv.fr/api/1/datasets/les-offres-diffusees-sur-choisir-le-service-public/"
SOURCE = "Choisir le Service Public"
FOLDER = ROOT / "data" / "opendata"
OFFER = "https://choisirleservicepublic.gouv.fr/offre-emploi/{}/"
SEARCH = "https://choisirleservicepublic.gouv.fr/nos-offres/filtres/mot-cles/{}/"
# (label in the description, column of the file)
DETAILS = [("Métier", "Métier"), ("Versant", "Versant"), ("Catégorie", "Catégorie"), ("Ouvert à", "Nature de l'emploi"),
           ("Durée du contrat", "Durée du contrat"), ("Niveau d'études", "Niveau d'études"),
           ("Expérience", "Niveau d'expérience min. requis"), ("Spécialisation", "Spécialisation"),
           ("Télétravail", "Télétravail"), ("Management", "Management"), ("Langues", "Langues"),
           ("Compétences attendues", "Compétences attendues"), ("Documents à transmettre", "Documents à transmettre")]


def _iso(value: str) -> str:
    try:
        return datetime.strptime((value or "").strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return ""


def posting(r: dict) -> dict | None:
    """One row of the file as an archive posting."""
    ref, title = (r.get("Référence") or "").strip(), (r.get("Intitulé du poste") or "").strip()
    if not ref or not title:
        return None
    place = next((r.get(c, "").strip() for c in ("Lieu d'affectation", "Lieu d'affectation (sans géolocalisation)",
                                                  "Localisation du poste") if r.get(c, "").strip()), "")
    open_to = (r.get("Nature de l'emploi") or "").strip()
    contract = ("Contractuel" if "uniquement aux contractuels" in open_to else
                "Titulaire ou contractuel" if "contractuel" in open_to.lower() else "Titulaire" if open_to else "")
    postcode = m.group(0) if (m := re.search(r"\b\d{5}\b", place)) else ""
    description = "\n".join(f"{label} : {r[col].strip()}" for label, col in DETAILS if (r.get(col) or "").strip())
    return {
        "id": f"csp:{ref}", "site": SOURCE, "source": SOURCE, "title": title,
        "company": (r.get("Employeur") or r.get("Organisme de rattachement") or "").strip(),
        "location": place, "postcode": postcode, "contract": contract,
        "posted": _iso(r.get("Date de première publication")) or _iso(r.get("Date de début de publication par défaut")),
        "url": (OFFER if re.fullmatch(r"\d{4}-\d+", ref) else SEARCH).format(ref), "apply_url": "",
        "description": description,
        "department_hint": (r.get("Localisation du poste") or "").strip(),
        "extra": {k: v for k, v in {
            "ends": _iso(r.get("Date de fin de publication par défaut")), "versant": r.get("Versant", "").strip(),
            "category": r.get("Catégorie", "").strip(), "job_family": r.get("Métier", "").strip(),
            "open_to": open_to, "contractuels": "contractuel" in open_to.lower(),
            "organisation": r.get("Organisme de rattachement", "").strip(),
            "status": r.get("Statut du poste", "").strip(), "reference": ref}.items() if v not in ("", None)},
    }


def latest_file() -> dict | None:
    """The newest offers file of the dataset (title offres-datagouv-YYYYMMDD.csv)."""
    data = requests.get(DATASET, timeout=30).json()
    files = [r for r in data.get("resources", []) if r.get("format") == "csv" and "offres-datagouv" in (r.get("title") or "")]
    return max(files, key=lambda r: r.get("last_modified") or "") if files else None


def import_file(arch, path, batch: int = 2000) -> int:
    """Every offer of a downloaded file into the archive; returns how many were new."""
    from .archive import department

    new, rows = 0, []
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            p = posting(r)
            if not p:
                continue
            hint = p.pop("department_hint")
            p["department"] = department(p["location"], p["postcode"]) or department(hint)
            rows.append(p)
            if len(rows) >= batch:
                new += arch.save(rows, lookups=0)  # départements come from the file: no town lookups in bulk
                rows = []
    return new + arch.save(rows, lookups=0)


def import_due(arch, every_hours: int = 24) -> int:
    """Called by the background thread: once a day, import the file if data.gouv.fr has a newer one."""
    checked = arch.get("csp_checked")
    now = datetime.now(timezone.utc)
    if checked and now - datetime.fromisoformat(checked) < timedelta(hours=every_hours):
        return 0
    arch.put("csp_checked", now.isoformat(timespec="seconds"))
    res = latest_file()
    if not res or res["id"] == arch.get("csp_file"):
        return 0
    FOLDER.mkdir(parents=True, exist_ok=True)
    path = FOLDER / "csp.csv"
    with requests.get(res["url"], stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    new = import_file(arch, path)
    arch.put("csp_file", res["id"])
    path.unlink(missing_ok=True)  # the next version is downloaded again; no need to keep 130 MB around
    log.info("%s: %d new public-sector offers from %s", SOURCE, new, res.get("title"))
    return new


def open_for(job: dict, today: str | None = None) -> bool:
    """A public-sector offer a candidate from outside the civil service can take: still published, open to
    contract staff (titulaire-only posts need the civil-servant status)."""
    today = today or date.today().isoformat()
    return (job.get("ends") or "9999") >= today and job.get("contractuels", True) is not False
