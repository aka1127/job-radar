"""Onboarding: a CV and a few answers in, a working candidate folder out. Claude is faked: it answers with the
example candidate's own files, which must pass the same checks as anything Claude writes."""
import pytest
import yaml

from hunter import onboard
from hunter.candidate import CANDIDATES

EXAMPLE_PROFILE = (CANDIDATES / "example" / "profile.yaml").read_text(encoding="utf-8")
EXAMPLE_CONFIG = (CANDIDATES / "example" / "config.yaml").read_text(encoding="utf-8")
CV = ("Alex Moreau - Product designer, Lyon. alex.moreau@example.com\n"
      + "Experience: Hexalab Santé, Senior Product Designer, Feb 2024 - Present. Designed the patient portal.\n" * 8)


class FakeClaude:
    def __init__(self, answers):
        self.answers, self.prompts = list(answers), []

    def __call__(self, cfg):  # stands in for the ClaudeCode class
        return self

    def run(self, step, prompt, schema=None, tools=()):
        self.prompts.append((step, prompt))
        return self.answers.pop(0)


ANSWERS = ("country: France\nhome: Lyon\ntargets: product designer\npriority_sector: healthcare\ncontracts: permanent\n"
           "languages: French native, English C1\n")


def files(tmp_path, answers=ANSWERS):
    cv, ans = tmp_path / "cv.txt", tmp_path / "answers.yaml"
    cv.write_text(CV, encoding="utf-8")
    ans.write_text(answers, encoding="utf-8")
    return cv, ans


def test_a_cv_becomes_a_checked_candidate_folder(tmp_path, monkeypatch):
    profile = "```yaml\n" + EXAMPLE_PROFILE + "\nonboarding_questions:\n  - How many usability sessions per month?\n```"
    fake = FakeClaude([profile, "Here you go:\n```yaml\n" + EXAMPLE_CONFIG + "```"])
    monkeypatch.setattr("hunter.llm.ClaudeCode", fake)
    cv, answers = files(tmp_path)
    folder = onboard.onboard("alex", cv, answers, root=tmp_path / "candidates")
    profile = yaml.safe_load((folder / "profile.yaml").read_text(encoding="utf-8"))
    config = yaml.safe_load((folder / "config.yaml").read_text(encoding="utf-8"))
    assert onboard.check_profile(profile) == [] and onboard.check_config(config) == []
    assert "onboarding_questions" not in profile and "usability sessions" in (folder / "QUESTIONS.md").read_text(encoding="utf-8")
    first, second = fake.prompts[0][1], fake.prompts[1][1]
    assert "never its facts" in first and "Hexalab Santé" in first and "priority_sector: healthcare" in first
    assert "country_code: FR" in first and "any field" in first and config["country"] == "FR"
    assert "Conditions are not facts" in first and "never infer a gender" in first
    assert "Hexalab" in second and fake.prompts[0][0] == "onboard"  # the profile feeds the settings


def test_a_broken_answer_is_sent_back_once_with_its_problems(tmp_path, monkeypatch):
    broken = EXAMPLE_CONFIG.replace("title_must_match: 'design", "title_must_match: '(design")  # unbalanced regex
    fake = FakeClaude([EXAMPLE_PROFILE, broken, EXAMPLE_CONFIG])
    monkeypatch.setattr("hunter.llm.ClaudeCode", fake)
    cv, answers = files(tmp_path)
    onboard.onboard("alex", cv, answers, root=tmp_path / "candidates")
    assert len(fake.prompts) == 3 and "title_must_match is not a valid regex" in fake.prompts[2][1]


def test_checks_catch_what_the_engine_needs():
    assert "missing 'experience'" in onboard.check_profile({})
    p = yaml.safe_load(EXAMPLE_PROFILE)
    p["experience"].append(dict(p["experience"][0]))  # the same id twice
    assert "experience ids must be unique lowercase slugs" in onboard.check_profile(p)
    c = yaml.safe_load(EXAMPLE_CONFIG) | {"default_family": "astronomy"}
    assert "default_family must be one of the families" in onboard.check_config(c)


def test_an_existing_person_is_never_overwritten_by_mistake(tmp_path):
    (tmp_path / "candidates" / "alex").mkdir(parents=True)
    cv, answers = files(tmp_path)
    with pytest.raises(SystemExit, match="already exists"):
        onboard.onboard("alex", cv, answers, root=tmp_path / "candidates")
    with pytest.raises(SystemExit, match="folder name"):
        onboard.onboard("Alex Moreau", cv, answers, root=tmp_path / "candidates")


def test_word_and_short_cvs(tmp_path):
    from docx import Document

    doc = Document()
    for line in CV.splitlines():
        doc.add_paragraph(line)
    doc.save(tmp_path / "cv.docx")
    assert "Hexalab" in onboard.cv_text(tmp_path / "cv.docx")
    (tmp_path / "scan.txt").write_text("too short", encoding="utf-8")
    with pytest.raises(SystemExit, match="scanned PDF"):
        onboard.cv_text(tmp_path / "scan.txt")


def test_the_interview_asks_the_country_first_and_follows_up_on_the_cv(tmp_path, monkeypatch):
    """No answers file: the questions are asked in the terminal, an unknown country is asked again, and Claude's
    follow-up questions about the CV are asked too, then folded into the profile."""
    profile = (EXAMPLE_PROFILE + "\nonboarding_questions:\n  - How many usability sessions per month?\n"
               "  - Your DN MADE dates?\n")
    fake = FakeClaude([profile, EXAMPLE_PROFILE, EXAMPLE_CONFIG])
    monkeypatch.setattr("hunter.llm.ClaudeCode", fake)
    monkeypatch.setattr(onboard, "_interactive", lambda: True)
    by_key = {"country": ["Atlantis", "Deutschland"], "home": ["Berlin"], "targets": ["data analyst"],
              "contracts": ["permanent"], "languages": ["German native, English C1"]}
    script = [a for key, *_ in onboard.QUESTIONS for a in by_key.get(key, [""])]
    typed = iter(script + ["about 10 a month", ""])  # follow-ups: one answered, one skipped
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt="": asked.append(prompt) or next(typed))
    cv, _ = files(tmp_path)
    folder = onboard.onboard("lena", cv, None, root=tmp_path / "candidates")
    assert asked[0].startswith("Which country") and asked[1].startswith("Which country")  # Atlantis: asked again
    assert "country_code: DE" in fake.prompts[0][1] and "Berlin" in fake.prompts[0][1]
    update = fake.prompts[1][1]
    assert "Q: How many usability sessions per month?" in update and "A: about 10 a month" in update
    assert "Your DN MADE dates?" in (folder / "QUESTIONS.md").read_text(encoding="utf-8")  # skipped: kept for later
    assert yaml.safe_load((folder / "config.yaml").read_text(encoding="utf-8"))["country"] == "DE"


def test_settings_must_use_known_countries_languages_and_contracts():
    c = yaml.safe_load(EXAMPLE_CONFIG)
    assert onboard.check_config(c) == []
    bad = c | {"country": "Atlantis", "cv_languages": ["en", "xx"], "contracts": ["CDI", "zero-hour"]}
    problems = "; ".join(onboard.check_config(bad))
    assert "ISO country code" in problems and "not xx" in problems and "not zero-hour" in problems
