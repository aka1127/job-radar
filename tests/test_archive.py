"""The national archive (every posting, every job) and the France Travail harvest that feeds it."""
from datetime import datetime, timedelta, timezone

import pytest

from hunter import archive, careers, harvest
from hunter.sources import job


@pytest.mark.parametrize("location, postcode, want", [
    ("Paris 09 - 75", "", "75"), ("Paris, 75011, 45 Rue Sedaine", "", "75"), ("", "97400", "974"),
    ("Ajaccio", "2A004", "2A"), ("Bastia", "20200", "2B"), ("75 - PARIS 11", "", "75"), ("Lyon 3e", "", "69"),
    ("Montigny-le-Bretonneux (78)", "", "78"), ("Remote, France", "", ""), ("Boulogne-Billancourt, Île-de-France", "", "92"),
])
def test_every_place_gets_its_departement(location, postcode, want):
    assert archive.department(location, postcode) == want


def test_postings_are_kept_once_with_the_longest_text(tmp_path):
    arch = archive.Archive(tmp_path / "jobs.db")
    a = job(id="indeed:1", site="indeed", title="Chef de projet", company="ACME", location="Paris 09 - 75",
            description="court")
    assert arch.save([a, job(id="indeed:2", site="indeed", title="Comptable", company="B", location="Lille")]) == 2
    assert arch.save([a | {"description": "une description beaucoup plus longue"}]) == 0  # seen again: not new
    row = arch.db.execute("select * from postings where id='indeed:1'").fetchone()
    assert row["description"] == "une description beaucoup plus longue" and row["department"] == "75"
    assert arch.save([a | {"description": ""}]) == 0
    assert arch.db.execute("select description from postings where id='indeed:1'").fetchone()[0].startswith("une")
    stats = arch.stats()
    assert stats["postings"] == 2 and stats["by_source"] == {"indeed": 2} and stats["by_department"]["59"] == 1


def test_harvest_pages_stay_inside_the_api_window():
    assert harvest.ranges(40) == [(0, 149)]
    assert harvest.ranges(1150)[-2:] == [(900, 1049), (1000, 1149)]
    assert all(s <= 1000 and e <= 1149 and e - s < 150 for s, e in harvest.ranges(5000))


class FakeFT:
    def headers(self):
        return {}

    def reset(self):
        pass


def offer(i: int) -> dict:
    return {"id": f"{i}X", "intitule": f"Offre {i}", "entreprise": {"nom": "ACME"}, "typeContrat": "CDI",
            "lieuTravail": {"libelle": "75 - Paris 11", "codePostal": "75011"}, "romeCode": "M1705",
            "dateCreation": "2026-10-31T08:00:00.000Z", "description": "Missions...",
            "salaire": {"libelle": "Annuel de 40000 Euros"}, "origineOffre": {"partenaires": [{"nom": "HELLOWORK"}]}}


def test_a_busy_day_is_cut_into_slices_so_no_offer_is_missed(tmp_path, monkeypatch):
    """2,000 offers in a day: more than the 1,150 one query returns, so the day is split and every offer arrives."""
    start = datetime(2026, 10, 31, tzinfo=timezone.utc)
    created = [start + timedelta(minutes=i * 0.72) for i in range(2000)]  # spread over the day
    calls = []

    class R:
        def __init__(self, offers, total):
            self.status_code = 206 if offers else 204
            self.headers = {"Content-Range": f"offres 0-0/{total}"}
            self._offers = offers

        def json(self):
            return {"resultats": self._offers}

        def raise_for_status(self):
            pass

    def get(url, params, headers, timeout):
        calls.append(params)
        lo = datetime.strptime(params["minCreationDate"], harvest.FMT).replace(tzinfo=timezone.utc)
        hi = datetime.strptime(params["maxCreationDate"], harvest.FMT).replace(tzinfo=timezone.utc)
        inside = [i for i, t in enumerate(created) if lo <= t < hi]
        s, e = map(int, params["range"].split("-"))
        return R([offer(i) for i in inside[s:e + 1]], len(inside))

    monkeypatch.setattr(harvest.requests, "get", get)
    monkeypatch.setattr(harvest.time, "sleep", lambda s: None)
    arch = archive.Archive(tmp_path / "jobs.db")
    new = harvest.Harvester(FakeFT(), arch).run(start, start + timedelta(days=1))
    assert new == 2000 and arch.stats()["postings"] == 2000
    assert all(int(c["range"].split("-")[0]) <= 1000 for c in calls)
    row = arch.db.execute("select * from postings where id='france_travail:7X'").fetchone()
    assert (row["contract"], row["rome"], row["department"], row["source"]) == ("CDI", "M1705", "75", "France Travail")
    assert "40000" in row["extra"] and "HELLOWORK" in row["extra"]
    assert arch.get("ft_harvest_until") == "2026-11-01T00:00:00Z"


def test_harvest_waits_quietly_without_api_access(tmp_path, monkeypatch):
    arch = archive.Archive(tmp_path / "jobs.db")

    class NoCredentials:
        enabled = False
    assert harvest.harvest_due(arch, NoCredentials()) == 0

    class Denied(FakeFT):
        enabled = True

    class R:
        status_code = 403
        headers = {}

        def raise_for_status(self):
            raise harvest.requests.HTTPError(response=self)
    monkeypatch.setattr(harvest.requests, "get", lambda *a, **k: R())
    monkeypatch.setattr(harvest.time, "sleep", lambda s: None)
    assert harvest.harvest_due(arch, Denied()) == 0


def test_career_pages_archive_every_job_but_return_only_matches(cand, monkeypatch):
    from hunter.store import Store

    store = Store(cand)
    store.add_company("greenhouse:acme", "ACME", "greenhouse", "acme", "https://boards.greenhouse.io/acme", "test")
    seen_filter = []

    def provider(slug, company, title_ok):
        seen_filter.append(title_ok("Comptable"))
        for t in ("Chef de projet marketing", "Comptable"):
            if title_ok(t):
                yield job(id=f"greenhouse:acme:{t}", site="career page (greenhouse)", title=t, company="ACME",
                          location="Paris")
    monkeypatch.setitem(careers.PROVIDERS, "greenhouse", provider)
    monkeypatch.setattr(careers.time, "sleep", lambda s: None)
    kept = []
    out = careers.poll(store, cand.config, lambda t: "marketing" in t.lower(), keep=kept.extend)
    assert [j["title"] for j in out] == ["Chef de projet marketing"]
    assert sorted(j["title"] for j in kept) == ["Chef de projet marketing", "Comptable"] and seen_filter == [True]


@pytest.mark.parametrize("location, want", [
    ("Maisons-Alfort, 94, France", "94"), ("Hauts-de-Seine, Île-de-France, France", "92"),
    ("Valbonne, 06, France", "06"), ("Télétravail, France", ""), ("France", "")])
def test_codes_and_departement_names_are_read(location, want):
    assert archive.department(location) == want


def test_unknown_towns_are_looked_up_once_within_their_region(tmp_path, monkeypatch):
    assert archive.town("St.-Denis, Île-de-France, France") == ("saint denis", "11")
    assert archive.town("Paris 15e Arrondissement") == ("paris", "")
    assert archive.town("Choisy-le-Roi IDF fr") == ("choisy le roi", "11")
    assert archive.town("Vanves Vanves France") == ("vanves", "")
    assert archive.town("Le Haillan Nouvelle-Aquitaine fr") == ("le haillan", "75")
    asked = []

    class R:
        def json(self):
            return [{"codeDepartement": "93"}]
    monkeypatch.setattr(archive.requests, "get", lambda url, params, timeout: asked.append(params) or R())
    arch = archive.Archive(tmp_path / "jobs.db")
    jobs = [job(id=f"x:{i}", site="linkedin", title="Chef de projet", company="A", location="St.-Denis, Île-de-France, France")
            for i in range(3)]
    arch.save(jobs)
    assert len(asked) == 1 and asked[0]["codeRegion"] == "11" and asked[0]["nom"] == "saint denis"  # cached after
    assert {r[0] for r in arch.db.execute("select department from postings")} == {"93"}


TALENTSOFT_FEED = b"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Offres</title>
<item><link>https://acme-career.talent-soft.com/Pages/Offre/detailoffre.aspx?idOffre=1</link>
<category>Marketing</category><category>CDI</category>
<title>2026-001 - Chef de projet marketing F/H</title>
<description>&lt;b&gt;Contrat : &lt;/b&gt;CDI&lt;br /&gt;&lt;b&gt;Localisation : &lt;/b&gt;Lyon&lt;br /&gt;""" + b"Missions " * 40 + b"""</description>
<pubDate>Fri, 30 Oct 2026 23:22:25 GMT</pubDate></item>
<item><link>https://acme-career.talent-soft.com/Pages/Offre/detailoffre.aspx?idOffre=2</link>
<category>CDI</category><title>2026-002 - Ingenieur</title><description>Localisation : Boston, USA</description>
<pubDate>Fri, 30 Oct 2026 10:00:00 GMT</pubDate></item>
</channel>"""


def test_employer_feeds_are_read_even_when_cut_short(monkeypatch):
    class R:
        ok, content = True, TALENTSOFT_FEED
    monkeypatch.setattr(careers, "get", lambda url, **kw: R())
    jobs = list(careers.rss("https://acme-career.talent-soft.com/handlers/offerRss.ashx?LCID=1036", "ACME", lambda t: True))
    assert [(j["title"], j["company"], j["location"], j.get("contract"), j["posted"]) for j in jobs] == [
        ("Chef de projet marketing F/H", "ACME", "Lyon", "CDI", "2026-10-30")]  # the Boston one is not in France
    assert jobs[0]["url"].endswith("idOffre=1") and len(jobs[0]["description"]) > 200


def test_career_sites_on_french_platforms_are_learned_from_apply_links(cand):
    from hunter.store import Store

    assert careers.site_source("https://framatome-career.talent-soft.com/offre-de-emploi/x_1.aspx") == (
        "rss:https://framatome-career.talent-soft.com/handlers/offerRss.ashx?LCID=1036", "rss",
        "https://framatome-career.talent-soft.com/handlers/offerRss.ashx?LCID=1036")
    assert careers.site_source("https://spartoo.nous-recrutons.fr/poste/abc")[1:] == ("jsonld", "https://spartoo.nous-recrutons.fr/")
    store = Store(cand)
    n = careers.learn(store, [job(id="i:1", site="indeed", title="x", company="Framatome",
                                  apply_url="https://framatome-career.talent-soft.com/offre-de-emploi/x_1.aspx")])
    row = store.db.execute("select * from companies where ats='rss'").fetchone()
    assert n == 1 and row["name"] == "Framatome" and row["slug"].endswith("offerRss.ashx?LCID=1036")


def test_sitemap_sites_are_read_once_and_reach_the_candidates(tmp_path, monkeypatch):
    from hunter import sitemaps

    sitemap = "<urlset>" + "".join(f"<url><loc>https://www.jobposting.pro/emploi-{i}-1</loc></url>" for i in (3, 2, 1)) + \
        "<url><loc>https://www.jobposting.pro/fonctionnalites</loc></url></urlset>"
    page = """<script type="application/ld+json">{"@type": "JobPosting", "title": "Chef de projet digital",
    "hiringOrganization": {"name": "Hirro"}, "datePosted": "2026-10-30",
    "jobLocation": {"address": {"addressLocality": "Paris", "postalCode": "75008"}}, "description": "Missions"}</script>"""
    opened = []

    class R:
        ok = True

        def __init__(self, text):
            self.text = text

    def get(url, **kw):
        opened.append(url)
        return R(sitemap if url.endswith(".xml") else page)
    monkeypatch.setattr(sitemaps.careers, "get", get)
    arch = archive.Archive(tmp_path / "jobs.db")
    site = dict(sitemaps.SITES[0])
    assert sitemaps.crawl(arch, site, pause=(0, 0)) == 3
    assert sitemaps.crawl(arch, site, pause=(0, 0)) == 0 and len(opened) == 5  # second pass: only the sitemap
    row = arch.db.execute("select * from postings where id='jobposting.pro:3'").fetchone()
    assert (row["source"], row["department"], row["company"]) == ("jobposting.pro", "75", "Hirro")
    recent = arch.recent("2000-01-01", ("jobposting.pro",))
    assert len(recent) == 3 and recent[0]["site"] == "jobposting.pro" and recent[0]["title"] == "Chef de projet digital"


CSP_CSV = """Organisme de rattachement;Référence;Versant;Métier;Statut du poste;Nature de l'emploi;Durée du contrat;Intitulé du poste;Localisation du poste;Lieu d'affectation;Niveau d'études;Niveau d'expérience min. requis;Date de vacance de l'emploi;Date de début de publication par défaut;Date de fin de publication par défaut;Date de première publication;Spécialisation;Télétravail;Management;Employeur;Catégorie;Temps Plein;Durée du poste;Langues;Niveaux;Lieu d'affectation (sans géolocalisation);Avis de vacances au JO;Compétences attendues;Documents à transmettre;Nature de contrat
Conseils régionaux;O033260101000001;Fonction Publique Territoriale;Chargée / Chargé de communication;Vacant;Emploi ouvert aux titulaires et aux contractuels;;Chargé de communication (H/F);Creuse (23);La Valette : 23320 Saint-Vaury;;;01/05/2026;01/10/2026;30/11/2026;01/10/2026;;Oui;;Région Nouvelle-Aquitaine;Catégorie B; Oui;;;;Saint-Vaury;;Rédaction, réseaux sociaux;;
INRAE;2026-2442551;Fonction Publique de l'Etat;Chargé de communication;Vacant;Emploi réservé aux fonctionnaires et lauréats d'un concours territorial;;Responsable communication (F/H);;75007 Paris;;;31/12/2025;01/10/2026;30/11/2026;01/10/2026;;;;INRAE;Catégorie A (cadre);;;;;75007 Paris;;;;
"""


def test_public_sector_open_data_is_imported_with_its_rules(tmp_path):
    from hunter import opendata

    path = tmp_path / "csp.csv"
    path.write_text(CSP_CSV, encoding="utf-8")
    arch = archive.Archive(tmp_path / "jobs.db")
    assert opendata.import_file(arch, path) == 2
    rows = {r["id"]: r for r in arch.db.execute("select * from postings")}
    region = rows["csp:O033260101000001"]
    assert (region["title"], region["company"], region["department"], region["contract"], region["posted"]) == (
        "Chargé de communication (H/F)", "Région Nouvelle-Aquitaine", "23", "Titulaire ou contractuel", "2026-10-01")
    assert region["url"].endswith("/mot-cles/O033260101000001/") and "Rédaction, réseaux sociaux" in region["description"]
    assert rows["csp:2026-2442551"]["url"] == "https://choisirleservicepublic.gouv.fr/offre-emploi/2026-2442551/"
    jobs = {j["id"]: j for j in arch.recent("2000-01-01", (opendata.SOURCE,))}
    assert opendata.open_for(jobs["csp:O033260101000001"], today="2026-10-31")
    assert not opendata.open_for(jobs["csp:2026-2442551"], today="2026-10-31")  # civil servants only
    assert not opendata.open_for(jobs["csp:O033260101000001"], today="2026-12-01")  # no longer published


CSP_FEED = b"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
<item><link>https://choisirleservicepublic.gouv.fr/offre-emploi/MINT_BA067ATB-113461/?tracking=1&amp;idOrigine=502</link>
<category>Communication/Chargee de communication</category><category>Emploi ouvert aux titulaires et aux contractuels</category>
<category>Hotel prefectoral, 5 place du Petit Broglie, 67000 STRASBOURG</category>
<title>MINT_BA067ATB-113461 - Charge de communication</title><description>Missions de communication</description>
<pubDate>Sat, 31 Oct 2026 08:00:00 GMT</pubDate></item>
<item><link>https://choisirleservicepublic.gouv.fr/offre-emploi/CNFPT-2/</link>
<category>Communication/Chef de projet</category><category>Emploi reserve aux fonctionnaires et laureats d'un concours territorial</category>
<category>67000 Strasbourg</category><title>CNFPT-2 - Chef de projet communication</title><description>x</description>
<pubDate>Sat, 31 Oct 2026 08:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_public_sector_feeds_keep_who_may_apply_and_name_the_employer(cand, monkeypatch):
    from hunter.store import Store

    offer = """<script type="application/ld+json">{"@type": "JobPosting", "title": "Charge de communication",
    "hiringOrganization": {"name": "Prefecture du Bas-Rhin"}}</script>"""

    class R:
        ok = True

        def __init__(self, url):
            self.content = CSP_FEED
            self.text = offer

    monkeypatch.setattr(careers, "get", lambda url, **kw: R(url))
    monkeypatch.setattr(careers.time, "sleep", lambda s: None)
    jobs = list(careers.csp("https://place-ep-recrute.talent-soft.com/handlers/offerRss.ashx?LCID=1036&Rss_JobDepartment=1",
                            "", lambda t: "communication" in t.lower()))
    first, second = jobs
    assert (first["id"], first["title"], first["company"], first["contract"], first["contractuels"]) == (
        "csp:MINT_BA067ATB-113461", "Charge de communication", "Prefecture du Bas-Rhin", "Titulaire ou contractuel", True)
    assert first["url"] == "https://choisirleservicepublic.gouv.fr/offre-emploi/MINT_BA067ATB-113461/"
    assert second["contractuels"] is False and second["contract"] == "Titulaire"
    # through the poll: archived both, but only the post open to contract staff reaches the candidate
    store = Store(cand)
    store.add_company("csp:x", "CSP (Bas-Rhin 67)", "csp", "https://x/feed", "https://x/feed", "test")
    kept = []
    out = careers.poll(store, cand.config, lambda t: "communication" in t.lower(), keep=kept.extend)
    assert [j["id"] for j in out] == ["csp:MINT_BA067ATB-113461"] and len(kept) == 2


def test_companies_add_takes_feeds_and_the_archive_learns_missing_employers(cand, tmp_path):
    from hunter.store import Store

    store = Store(cand)
    feed = "https://fnacdarty-recrute.talent-soft.com/handlers/offerRss.ashx?LCID=1036"
    assert careers.add_url(store, feed, "Fnac Darty") == feed
    assert store.db.execute("select ats, slug from companies where name='Fnac Darty'").fetchone()[:] == ("rss", feed)
    arch = archive.Archive(tmp_path / "jobs.db")
    arch.save([job(id="csp:1", site="csp", title="Chargé de communication", company="", location="Lyon")])
    arch.save([job(id="csp:1", site="csp", title="Chargé de communication", company="Ville de Lyon", location="Lyon")])
    assert arch.db.execute("select company from postings").fetchone()[0] == "Ville de Lyon"


def test_impact_jobs_are_read_in_french_once():
    from hunter import sitemaps

    site = next(s for s in sitemaps.SITES if s["name"] == "Jobs that make sense")
    fr = "https://jobs.makesense.org/fr/jobs/wind-fisher-forum-aeropsace-hf-00skfsxMpyw9ubX4LhN3"
    assert sitemaps.offer_id(site, fr) == "Jobs that make sense:00skfsxMpyw9ubX4LhN3"
    assert not site["offer"].search(fr.replace("/fr/", "/en/"))  # the English copy of the same offer is skipped
