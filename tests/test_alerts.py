import email
from email.message import EmailMessage

from hunter import alerts
from hunter.store import Store

WTTJ = "https://www.welcometothejungle.com/fr/companies/acme/jobs/charge-de-marketing-digital_paris"


def _mail(sender: str, html: str) -> bytes:
    m = EmailMessage()
    m["From"], m["Subject"] = sender, "Nouvelles offres"
    m.set_content("see html")
    m.add_alternative(html, subtype="html")
    return bytes(m)


class FakeIMAP:
    mails: dict[int, bytes] = {}

    def __init__(self, host, timeout=None):
        self.host = host

    def login(self, user, password):
        pass

    def select(self, folder, readonly=False):
        assert readonly  # alerts are never marked as read
        return "OK", [b"2"]

    def uid(self, command, *args):
        if command == "search":
            query = args[-1]
            low = int(query.split()[1].split(":")[0]) if query.startswith("UID") else 1
            return "OK", [b" ".join(str(u).encode() for u in sorted(self.mails) if u >= low)]
        uid = int(args[0])
        return "OK", [(f"{uid} (BODY[] {{1}}".encode(), self.mails[uid]), b")"]

    def logout(self):
        pass


def test_job_links_are_recognised():
    assert alerts.job_link(WTTJ + "?utm_source=alert&o=1") == ("wttj", WTTJ)
    assert alerts.job_link("https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=x") == \
        ("linkedin", "https://www.linkedin.com/jobs/view/4012345678")
    assert alerts.job_link("https://www.apec.fr/candidat/recherche-emploi.html/emploi/detail-offre/176543210W?x=1")[0] \
        == "apec"
    assert alerts.job_link("https://www.welcometothejungle.com/fr/me/settings") is None


def test_links_of_the_other_alert_boards_are_recognised():
    """Offer links as the boards printed them on 31 Oct 2026, with alert tracking added."""
    assert alerts.job_link("https://www.cadremploi.fr/emploi/detail_offre?xtor=EREC-1&offreId=156563179300913944") == \
        ("cadremploi", "https://www.cadremploi.fr/emploi/detail_offre?offreId=156563179300913944")
    assert alerts.job_link("https://www.hellowork.com/fr-fr/emplois/84737871.html?utm_source=alerte") == \
        ("hellowork", "https://www.hellowork.com/fr-fr/emplois/84737871.html")
    assert alerts.job_link("https://www.meteojob.com/jobs/57814739?utm_medium=email") == \
        ("meteojob", "https://www.meteojob.com/jobs/57814739")
    assert alerts.job_link("https://fr.indeed.com/rc/clk/dl?jk=2630830c423df8a7&from=ja&qd=x") == \
        ("indeed", "https://fr.indeed.com/viewjob?jk=2630830c423df8a7")
    tracked = "https://t.example.com/r?u=https%3A%2F%2Ffr.indeed.com%2Fpagead%2Fclk%3Fmo%3Dr%26jk%3D0123456789abcdef"
    assert alerts.job_link(tracked) == ("indeed", "https://fr.indeed.com/viewjob?jk=0123456789abcdef")
    assert alerts.job_link("https://www.hellowork.com/fr-fr/candidat/mes-alertes.html") is None
    assert {"cadremploi", "indeed"} <= alerts.BLOCKS_BOTS and "hellowork" not in alerts.BLOCKS_BOTS


def test_a_cadremploi_alert_is_read_from_the_email(cand, monkeypatch):
    monkeypatch.setenv("ALERTS_IMAP_USER", "alerts@example.com")
    monkeypatch.setenv("ALERTS_IMAP_PASSWORD", "app-password")
    offer = "https://www.cadremploi.fr/emploi/detail_offre?offreId=156563179300913944"
    FakeIMAP.mails = {3: _mail("Cadremploi <alertes@cadremploi.fr>",
                               f'<table><tr><td><a href="https://click.cadremploi.fr/c/xyz">Chef de projet digital H/F</a>'
                               f'<br><span>ACME Media</span><br><span>Paris 08 - 75</span><br><span>CDI · 50 k€</span>'
                               f'<p>Vous pilotez la refonte du site et les campagnes digitales.</p></td></tr></table>')}
    monkeypatch.setattr(alerts.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(alerts, "_resolve", lambda url: offer + "&xtor=EREC")
    monkeypatch.setattr(alerts, "to_job", lambda *a: (_ for _ in ()).throw(AssertionError("Cadremploi pages refuse bots")))
    [job] = alerts.collect(cand, Store(cand))
    assert (job["title"], job["company"], job["location"], job["url"]) == \
        ("Chef de projet digital H/F", "ACME Media", "Paris 08 - 75", offer)
    assert job["summary_only"] and job["site"] == "email alert (cadremploi)"


def test_alerts_become_jobs_once(cand, monkeypatch):
    monkeypatch.setenv("ALERTS_IMAP_USER", "alerts@example.com")
    monkeypatch.setenv("ALERTS_IMAP_PASSWORD", "app-password")
    FakeIMAP.mails = {
        1: _mail("Welcome to the Jungle <alerts@welcometothejungle.com>",
                 f'<a href="{WTTJ}?utm=1">Chargé de marketing digital</a>'
                 f'<a href="https://click.wttj.example/ls/click?upn=abc">CRM Manager</a>'
                 f'<a href="https://www.welcometothejungle.com/fr/me/settings">Settings</a>'),
        2: _mail("A friend <friend@gmail.com>", f'<a href="{WTTJ.replace("acme", "other")}">look</a>'),
    }
    monkeypatch.setattr(alerts.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(alerts, "_resolve", lambda url: WTTJ.replace("charge-de-marketing-digital", "crm-manager"))
    monkeypatch.setattr(alerts, "to_job", lambda board, url: {"id": f"alert:{url}", "title": url.rsplit("/", 1)[1],
                                                              "company": "Acme", "description": "x" * 300})
    store = Store(cand)
    jobs = alerts.collect(cand, store)
    assert [j["title"] for j in jobs] == ["charge-de-marketing-digital_paris", "crm-manager_paris"]  # friend skipped
    assert store.get("alerts_uid") == "2"
    assert alerts.collect(cand, store) == []  # nothing new since


def test_no_mailbox_no_problem(cand):
    assert not alerts.enabled(cand) and alerts.collect(cand, Store(cand)) == []


APEC_MAIL = """<table>
 <tr><td>
  <a href="https://e.apec.fr/c/abc123">Chargé de marketing digital H/F</a><br>
  <span>ACME Retail</span><br><span>Paris 08 - 75</span><br><span>CDI · 45 - 50 k€ brut annuel</span>
  <p>Rattaché au responsable acquisition, vous pilotez les campagnes SEA, CRM et emailing de la marque.</p>
  <a href="https://e.apec.fr/c/abc123">Voir l'offre</a>
 </td></tr>
 <tr><td>
  <a href="https://e.apec.fr/c/def456">Responsable CRM F/H</a><br>
  <span>Beta Bank</span><br><span>Lyon - 69</span><br><span>CDD</span>
  <p>Vous animez le programme de fidélisation et les scénarios automatisés.</p>
 </td></tr>
 <tr><td><a href="https://e.apec.fr/c/unsub">Se désinscrire</a></td></tr>
</table>"""


def test_apec_offers_are_read_from_the_alert_email(cand, monkeypatch):
    monkeypatch.setenv("ALERTS_IMAP_USER", "alerts@example.com")
    monkeypatch.setenv("ALERTS_IMAP_PASSWORD", "abcd efgh ijkl mnop")
    FakeIMAP.mails = {7: _mail("APEC <offres@apec.fr>", APEC_MAIL)}
    monkeypatch.setattr(alerts.imaplib, "IMAP4_SSL", FakeIMAP)
    base = "https://www.apec.fr/candidat/recherche-emploi.html/emploi/detail-offre/"
    targets = {"abc123": base + "111111W?xtor=alert", "def456": base + "222222W", "unsub": "https://www.apec.fr/compte"}
    monkeypatch.setattr(alerts, "_resolve", lambda url: targets[url.rsplit("/", 1)[1]])
    monkeypatch.setattr(alerts, "to_job", lambda *a: (_ for _ in ()).throw(AssertionError("APEC pages are never fetched")))
    jobs = alerts.collect(cand, Store(cand))
    assert [(j["title"], j["company"], j["location"]) for j in jobs] == [
        ("Chargé de marketing digital H/F", "ACME Retail", "Paris 08 - 75"), ("Responsable CRM F/H", "Beta Bank", "Lyon - 69")]
    first = jobs[0]
    assert first["id"] == f"alert:{base}111111W" and first["summary_only"] and first["site"] == "email alert (apec)"
    assert "45 - 50 k€" in first["description"] and "Voir l'offre" not in first["description"]


def test_summary_only_jobs_pass_the_description_gate_and_say_so(cand, tmp_path):
    from hunter import notify, pipeline
    from hunter.store import Store as S

    job = {"id": "alert:x", "site": "email alert (apec)", "title": "Chargé CRM H/F", "company": "ACME",
           "location": "Paris - 75", "url": "https://www.apec.fr/x", "apply_url": "", "description": "short",
           "posted": "", "summary_only": True}
    assert pipeline.with_descriptions([job], S(cand), cand.config, dry=True) == [job]
    fit = {"score": 70, "why_fit": ["CRM"], "gaps": [], "contract": "CDI"}
    res = {"tier": 1, "lang": "fr", "ats": {"score": 80}, "screen": {"score": 75}, "flags": [],
           "pack": {"hiring_manager_titles": ["CMO"]}}
    assert "read the full posting before applying" in notify.card(job, fit, res)


def _apec_link(n: int, payload: str) -> str:
    import base64
    return f"https://neomarket.diffusion.apec.fr/r/?id=h294,18b5,{n}&e={base64.b64encode(payload.encode()).decode()}&s=x"


def test_apec_tracking_links_are_decoded_and_grouped_per_offer():
    """The real APEC alert (Oct 2026): every offer is 4 tracking links (title, company, contract, place) whose `e`
    parameter is base64 for the offer number. No page is fetched."""
    offer = "p1=www.apec.fr&p2=179687361W&p3=&xtor=EPR-41-[push_avec_compte]"
    search = "p1=www.apec.fr&p2=14204134&p3=&xtor=EPR-41"
    rows = "".join(f'<tr><td><a href="{_apec_link(i, offer)}">{t}</a></td></tr>'
                   for i, t in enumerate(["Chargé(e) de marketing Go To Market F/H", "SIPARTECH", "CDI •", "Paris 09 - 75"]))
    html = (f'<div><table>{rows}</table></div><div><table><tr><td><a href="{_apec_link(9, offer.replace("179687361W", "179689117W"))}">'
            f'Consultant Salesforce Marketing Cloud F/H</a></td></tr><tr><td><a href="{_apec_link(10, offer.replace("179687361W", "179689117W"))}">'
            f'Act Digital France</a></td></tr><tr><td><a href="{_apec_link(11, offer.replace("179687361W", "179689117W"))}">Lyon 01 - 69</a>'
            f'</td></tr></table></div><a href="{_apec_link(12, search)}">Voir toutes les offres correspondantes</a>')
    msg = email.message_from_bytes(_mail("APEC <offres@diffusion.apec.fr>", html))
    assert alerts.job_link(_apec_link(12, search)) is None  # "see all offers" is a search, not an offer
    seen, jobs = set(), []
    for url, text, block in alerts.links_in(msg):
        hit = alerts.job_link(url)
        if hit and hit[1] not in seen:
            seen.add(hit[1])
            jobs.append(alerts.from_block(*hit, text, block, "2026-10-31"))
    assert [(j["title"], j["company"], j["location"]) for j in jobs] == [
        ("Chargé(e) de marketing Go To Market F/H", "SIPARTECH", "Paris 09 - 75"),
        ("Consultant Salesforce Marketing Cloud F/H", "Act Digital France", "Lyon 01 - 69")]
    assert jobs[0]["url"].endswith("/detail-offre/179687361W") and jobs[0]["summary_only"]
