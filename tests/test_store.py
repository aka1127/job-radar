from hunter.store import Store, dedupe_key

METRO_A = {"id": "hellowork:1", "site": "hellowork", "title": "Chef de Projet Acquisition Solutions Digitales H/F",
           "company": "METRO France", "location": "Paris", "url": "https://a"}
METRO_B = {"id": "indeed:2", "site": "indeed", "title": "Chef de projet acquisition Solutions Digitales F/H",
           "company": "METRO", "location": "Paris", "url": "https://b"}


def test_one_job_on_two_boards_is_one_job():
    assert dedupe_key(METRO_A) == dedupe_key(METRO_B)
    assert dedupe_key({"company": "Thales Group", "title": "Content Marketing Specialist H/F"}) == \
        dedupe_key({"company": "Thales", "title": "Content Marketing Specialist (F/H)"})
    assert dedupe_key({"company": "Air Liquide", "title": "CRM Manager"}) != \
        dedupe_key({"company": "Air France", "title": "CRM Manager"})


def test_a_twin_of_a_sent_job_is_not_sent_again(cand):
    store = Store(cand)
    store.save(METRO_A, "sent", 74, 1, {})
    assert not store.is_new(METRO_B)
    store.save(METRO_B, "queued", 72, 1, {})
    assert store.twin_sent(METRO_B["id"], dedupe_key(METRO_B))
    assert not store.twin_sent(METRO_A["id"], dedupe_key(METRO_A))


def test_old_keys_are_migrated(cand):
    store = Store(cand)
    store.save(METRO_A, "sent", 74, 1, {})
    store.db.execute("update jobs set key='metro france|old'")
    store.put("key_version", "1")
    store = Store(cand)
    assert store.db.execute("select key from jobs").fetchone()[0] == dedupe_key(METRO_A)


def test_a_repost_under_another_company_name_is_a_duplicate(cand):
    from hunter.sources import job
    from hunter.store import Store

    store = Store(cand)
    text = " ".join(f"mot{i}" for i in range(120)) + " Pomelo-Paradigm accompagne les sociétés du CAC40."
    original = job(id="indeed:1", site="indeed", title="Digital Marketing Specialist H/F", company="Pomelo-Paradigm",
                   description=text)
    repost = job(id="indeed:2", site="indeed", title="Digital Marketing Specialist (F/H)", company="Agence XYZ",
                 description="Description\n\n" + text + " Postulez vite.")
    other = job(id="indeed:3", site="indeed", title="Digital Marketing Specialist H/F", company="Autre",
                description=" ".join(f"autre{i}" for i in range(120)))
    store.save(original, "sent", 80, 1)
    assert store.repost_sent(repost) and not store.repost_sent(other)
    assert not store.repost_sent(original)  # never its own duplicate


def test_postings_waiting_too_long_for_a_score_expire(cand):
    from hunter.sources import job

    store = Store(cand)
    store.save(job(id="x:old", title="Chef de projet", company="A"), "pending")
    store.save(job(id="x:new", title="Chargé CRM", company="B"), "pending")
    store.db.execute("update jobs set first_seen='2026-10-01T08:00:00+00:00' where id='x:old'")
    assert [j["id"] for j in store.pending(7)] == ["x:new"]
    assert store.db.execute("select status from jobs where id='x:old'").fetchone()[0] == "expired"


def test_a_longer_or_shorter_spelling_of_the_employer_is_the_same_job(cand):
    """31 Oct 2026: Indeed said 'Adagio Aparthotel' and 'Levertech (Groupe LV Technologies)', Glassdoor said 'ADAGIO'
    and 'Levertech', each with a short description."""
    from hunter.sources import job
    from hunter.store import same_company

    assert same_company("ADAGIO", "Adagio Aparthotel") and same_company("Levertech (Groupe LV Technologies)", "Levertech")
    assert not same_company("Air Liquide", "Air France") and not same_company("SNCF", "SN")
    store = Store(cand)
    store.save(job(id="indeed:a", site="indeed", title="Chef de projet Marketing BtoB (F/H/X) - CDD",
                   company="Adagio Aparthotel", description="court"), "sent", 74, 1)
    twin = job(id="glassdoor:a", site="glassdoor", title="Chef de projet Marketing BtoB (F/H/X) - CDD",
               company="ADAGIO", description="autre texte court")
    other_job = job(id="glassdoor:b", site="glassdoor", title="Chef de projet Marketing BtoC", company="ADAGIO")
    assert store.repost_sent(twin) and not store.repost_sent(other_job)
