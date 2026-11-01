from hunter import careers


def test_ats_links_are_recognised():
    assert careers.parse_ats_url("https://jobs.eu.lever.co/jacquemus/abc") == ("lever", "jacquemus")
    assert careers.parse_ats_url("https://job-boards.eu.greenhouse.io/payhawkio/jobs/1") == ("greenhouse", "payhawkio")
    assert careers.parse_ats_url("https://jobs.ashbyhq.com/alan/35d2") == ("ashby", "alan")
    assert careers.parse_ats_url("https://yousign.teamtailor.com/jobs/1-x") == ("teamtailor", "yousign")
    assert careers.parse_ats_url("https://www.linkedin.com/jobs/view/1") is None


def test_board_names_are_cleaned():
    assert careers.clean_name("Offres d'emploi disponibles - Groupe Galeries Lafayette") == "Groupe Galeries Lafayette"
    assert careers.clean_name("Ledger Jobs") == "Ledger"
    assert careers.clean_name("Careers at Mistertemp") == "Mistertemp"
    assert careers.clean_name("JACQUEMUS") == "Jacquemus"
    assert careers.clean_name("BETC") == "BETC"
    assert careers.clean_name("Pennylane SAS") == "Pennylane"
    assert careers.clean_name("lemlist") == "Lemlist"


def test_job_posting_data_is_read():
    d = {"@type": "JobPosting", "title": "Chargé de marketing digital &amp; CRM",
         "hiringOrganization": {"@type": "Organization", "name": "EGYM"},
         "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "Paris",
                                                       "addressCountry": "FR"}},
         "datePosted": "2026-10-29T08:00:00Z", "description": "&lt;p&gt;Rejoignez-nous &amp;amp; grandissez&lt;/p&gt;"}
    j = careers.from_posting(d, "https://example.com/job/1", "career page")
    assert j["title"] == "Chargé de marketing digital & CRM" and j["company"] == "EGYM"
    assert j["location"] == "Paris, FR" and j["posted"] == "2026-10-29"
    assert j["description"] == "Rejoignez-nous & grandissez"  # sites often escape their HTML twice
    assert careers.in_france(j["location"])


def test_crawler_reads_job_pages_first_and_skips_seen_ones(monkeypatch):
    listing = """<a href="/emplois/seo">SEO</a><a href="/emplois/seo/acme/consultant-seo">Consultant SEO</a>
                 <a href="/emplois/crm/acme/crm-manager">CRM Manager</a><a href="/about">About us</a>"""
    posting = ('<script type="application/ld+json">{"@type": "JobPosting", "title": "Consultant SEO", '
               '"jobLocation": {"address": {"addressLocality": "Paris"}}}</script>')
    fetched = []

    class Page:
        ok = True

        def __init__(self, url, text):
            self.url, self.text = url, text

    def get(url, **kw):
        fetched.append(url)
        return Page(url, listing if url.endswith("/emplois/in/paris") else posting)

    monkeypatch.setattr(careers, "get", get)
    monkeypatch.setattr(careers.time, "sleep", lambda s: None)
    seen = {"https://board.test/emplois/crm/acme/crm-manager"}
    jobs = list(careers.jsonld("https://board.test/emplois/in/paris", "Board", lambda t: True, max_pages=1,
                               seen=seen.__contains__))
    assert fetched[1] == "https://board.test/emplois/seo/acme/consultant-seo"  # deepest unseen page first
    assert len(fetched) == 2 and jobs[0]["company"] == "Board"  # no hiringOrganization: falls back to the board


def test_workday_boards_are_read_for_france_only(monkeypatch):
    """A large group's Workday career site, read through the public JSON API behind its own pages."""
    assert careers.parse_ats_url("https://acme.wd5.myworkdayjobs.com/fr-FR/AcmeFR/job/x") == ("workday", "acme.wd5/AcmeFR")
    listing = {"total": 3, "jobPostings": [
        {"title": "Chef de projet digital H/F", "externalPath": "/job/Paris/Chef_1", "locationsText": "Paris, France"},
        {"title": "Sales Manager", "externalPath": "/job/London/Sales_2", "locationsText": "London, UK"},
        {"title": "Stage marketing", "externalPath": "/job/Paris/Stage_3", "locationsText": "Paris, France"}]}
    detail = {"jobPostingInfo": {"title": "Chef de projet digital H/F", "location": "Paris, France", "jobReqId": "ACME-1",
                                 "startDate": "2026-10-20", "externalUrl": "https://acme.wd5.myworkdayjobs.com/AcmeFR/job/1",
                                 "jobDescription": "<p>Lancement de la nouvelle plateforme</p>"}}

    class R:
        ok = True

        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    posts, gets = [], []
    monkeypatch.setattr(careers.requests, "post", lambda url, **kw: posts.append(kw["json"]) or R(listing))
    monkeypatch.setattr(careers.requests, "get", lambda url, **kw: gets.append(url) or R(detail))
    jobs = list(careers.workday("acme.wd5/AcmeFR", "Acme France", lambda t: "stage" not in t.lower()))
    assert [(j["title"], j["company"], j["posted"]) for j in jobs] == [
        ("Chef de projet digital H/F", "Acme France", "2026-10-20")]
    assert jobs[0]["description"] == "Lancement de la nouvelle plateforme" and jobs[0]["id"] == "workday:acme.wd5/AcmeFR:ACME-1"
    assert gets == ["https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/AcmeFR/job/Paris/Chef_1"]  # one detail fetch
    assert posts[0]["searchText"] == ""


def test_profilculture_offers_are_read_from_their_layout():
    page = """<html><body><h2>Radio France - ProfilCulture</h2><p>détail de l'</p><p>offre</p>
    <p>Chargé.e de communication</p><p>A mon tour prod</p><p>Paris 3e</p><p>29/10/26</p><p>Urgent</p><p>CDI</p>
    <p>Retour aux offres</p><p>Secteur</p><p>Spectacle vivant</p><p>Description du poste</p>
    <p>Promotion des tournées et des sorties d'albums.</p><p>Postulez</p><p>Les dernières actualités</p></body></html>"""
    j = careers.profilculture_job("https://www.profilculture.com/annonce/charge-e-de-communication-500900.html", page)
    assert (j["title"], j["company"], j["location"], j["posted"]) == ("Chargé.e de communication", "A mon tour prod",
                                                                    "Paris 3e", "2026-10-29")
    assert j["id"] == "profilculture:500900" and j["description"].startswith("Contrat : CDI\nSecteur")
    assert "Postulez" not in j["description"] and "actualités" not in j["description"]


def test_welcome_to_the_jungle_pages_open_only_new_matching_offers(monkeypatch):
    listing = """<a href="/fr/companies/brainsonic/jobs/chef-de-projet-social-media_paris"><img></a>
    <a href="/fr/companies/brainsonic/jobs/chef-de-projet-social-media_paris">Chef de Projet Social Media (H/F/X) CDI</a>
    <a href="/fr/companies/acme/jobs/developpeur-python_paris">Développeur Python</a>
    <a href="/fr/companies/old/jobs/social-media-manager_lyon">Social Media Manager</a>
    <a href="/fr/pages/emploi-marketing">Marketing</a>"""
    offer = """<script type="application/ld+json">{"@type": "JobPosting", "title": "Chef de Projet Social Media (H/F/X) CDI",
    "hiringOrganization": {"name": "Brainsonic"}, "datePosted": "2026-10-31",
    "jobLocation": {"address": {"addressLocality": "Paris", "addressCountry": "FR"}},
    "description": "<p>Pilotage des r\u00e9seaux sociaux de grandes marques.</p>"}</script>"""
    opened = []

    class R:
        ok, status_code = True, 200

        def __init__(self, url, text):
            self.url, self.text = url, text

    def get(url, **kw):
        opened.append(url)
        return R(url, listing if "/pages/" in url else offer)
    monkeypatch.setattr(careers, "get", get)
    monkeypatch.setattr(careers.time, "sleep", lambda s: None)
    monkeypatch.setattr(careers, "_wttj_rest_until", 0.0)
    seen = {"https://www.welcometothejungle.com/fr/companies/old/jobs/social-media-manager_lyon"}
    jobs = list(careers.wttj("emploi-social-media-manager", "WTTJ", lambda t: "python" not in t.lower(), seen=seen.__contains__))
    assert [(j["title"], j["company"], j["site"]) for j in jobs] == [
        ("Chef de Projet Social Media (H/F/X) CDI", "Brainsonic", "Welcome to the Jungle")]
    assert jobs[0]["id"] == "wttj:chef-de-projet-social-media_paris" and jobs[0]["posted"] == "2026-10-31"
    assert opened == ["https://www.welcometothejungle.com/fr/pages/emploi-social-media-manager",
                      "https://www.welcometothejungle.com/fr/companies/brainsonic/jobs/chef-de-projet-social-media_paris"]



def test_welcome_to_the_jungle_bot_check_is_respected(monkeypatch):
    class Challenge:
        ok, status_code, text, url = True, 202, "", ""

    calls = []
    monkeypatch.setattr(careers, "get", lambda url, **kw: calls.append(url) or Challenge())
    monkeypatch.setattr(careers, "_wttj_rest_until", 0.0)
    assert list(careers.wttj("emploi-marketing", "WTTJ", lambda t: True)) == []
    assert list(careers.wttj("emploi-crm-manager", "WTTJ", lambda t: True)) == []
    assert len(calls) == 1  # after one 202 the board rests: no second request


def test_robots_rules_decide_which_pages_are_opened(monkeypatch):
    import importlib

    import hunter.careers as c

    real = importlib.reload(c)  # the real allowed(), not the test stub
    try:
        robots = {"https://a.fr": (200, "User-agent: *\nDisallow: /search\nDisallow: /*?"),
                  "https://b.fr": (404, ""), "https://c.fr": (503, "")}
        calls = []

        class R:
            def __init__(self, code, text):
                self.status_code, self.text, self.ok = code, text, code < 400

        def get(url, headers=None, timeout=None):
            base = url.rsplit("/robots.txt", 1)[0]
            calls.append(base)
            return R(*robots[base])
        monkeypatch.setattr(real.requests, "get", get)
        real._robots.clear()
        assert real.allowed("https://a.fr/emploi/123") and not real.allowed("https://a.fr/search")
        assert not real.allowed("https://a.fr/emploi?page=2")
        assert real.allowed("https://b.fr/anything")  # no robots.txt: allowed
        assert not real.allowed("https://c.fr/anything")  # robots.txt failing: not now
        assert calls.count("https://a.fr") == 1  # read once, then cached
    finally:
        real._robots.clear()


def test_offer_text_keeps_the_main_content():
    page = ("<html><body><nav>Accueil Offres Connexion</nav><main><h1>Chargé de communication</h1>"
            + "<p>Vous pilotez la communication digitale de la collectivité, les réseaux sociaux et les relations presse. "
            * 6 + "</p></main><footer>Mentions légales Cookies</footer></body></html>")
    text = careers.page_text(page)
    assert "réseaux sociaux" in text and "Mentions légales" not in text and "Connexion" not in text


def test_career_platforms_are_read_side_by_side(cand, monkeypatch):
    import threading

    from hunter.store import Store

    store = Store(cand)
    store.add_company("greenhouse:a", "A", "greenhouse", "a", "https://boards.greenhouse.io/a", "test")
    store.add_company("lever:b", "B", "lever", "b", "https://jobs.lever.co/b", "test")
    together = threading.Barrier(2, timeout=5)  # passes only if both platforms are read at the same time

    def provider(slug, company, title_ok):
        together.wait()
        yield from ()
    monkeypatch.setitem(careers.PROVIDERS, "greenhouse", provider)
    monkeypatch.setitem(careers.PROVIDERS, "lever", provider)
    monkeypatch.setattr(careers.time, "sleep", lambda s: None)
    assert careers.poll(store, cand.config, lambda t: True) == [] and not together.broken
    assert all(r["polled"] for r in store.db.execute("select polled from companies"))  # recorded by the caller


def test_a_platform_stops_at_its_time_budget(cand, monkeypatch):
    from hunter.store import Store

    store = Store(cand)
    for i in range(3):
        store.add_company(f"greenhouse:{i}", f"C{i}", "greenhouse", str(i), f"https://x/{i}", "test")
    clock = iter([0, 0, 1000, 2000, 3000, 4000])  # the second board starts after the budget is spent
    monkeypatch.setattr(careers.time, "time", lambda: next(clock))
    monkeypatch.setattr(careers.time, "sleep", lambda s: None)
    monkeypatch.setitem(careers.PROVIDERS, "greenhouse", lambda slug, company, title_ok: iter(()))
    cand.config["career_pages"]["max_minutes_per_run"] = 10
    careers.poll(store, cand.config, lambda t: True)
    polled = [r["key"] for r in store.db.execute("select key from companies where polled is not null")]
    assert len(polled) == 1  # the other two stay due for the next run


def test_a_platform_waiting_for_a_thread_gets_no_extra_time(cand, monkeypatch):
    """13 platforms and fewer threads: one that starts late must not restart the 15 minutes."""
    from hunter.store import Store

    store = Store(cand)
    store.add_company("greenhouse:a", "A", "greenhouse", "a", "https://x/a", "test")
    store.add_company("lever:b", "B", "lever", "b", "https://x/b", "test")
    clock = iter([0, 0, 1000, 1000, 1000])  # lever starts after greenhouse used the whole budget
    monkeypatch.setattr(careers.time, "time", lambda: next(clock))
    monkeypatch.setattr(careers.time, "sleep", lambda s: None)
    for ats in ("greenhouse", "lever"):
        monkeypatch.setitem(careers.PROVIDERS, ats, lambda slug, company, title_ok: iter(()))
    cand.config["career_pages"]["max_minutes_per_run"] = 10
    careers.poll(store, cand.config, lambda t: True, workers=1)
    assert [r["key"] for r in store.db.execute("select key from companies where polled is not null")] == ["greenhouse:a"]
