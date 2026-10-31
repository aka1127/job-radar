from hunter.ats import role_title
from hunter.candidate import file_part
from hunter.pipeline import file_tag, tidy_skills, title_filter


def test_ai_never_gets_its_own_skills_group():
    skills = [{"label": "CRM & Automation", "items": ["HubSpot"]},
              {"label": "AI & Content", "items": ["ChatGPT", "Copywriting"]},
              {"label": "Outils IA", "items": ["ChatGPT", "Contenu assisté par IA", "Midjourney"]}]
    assert tidy_skills(skills) == [{"label": "CRM & Automation", "items": ["HubSpot"]},
                                   {"label": "Content", "items": ["ChatGPT", "Copywriting", "Contenu assisté par IA"]}]
    assert tidy_skills([{"label": "Data & Analytics", "items": ["GA4"]}]) == [{"label": "Data & Analytics",
                                                                              "items": ["GA4"]}]
from hunter.text import detect_lang, display_title


def test_display_title_drops_gender_and_contract_marks():
    assert display_title("Chargé de marketing digital (H/F)") == "Chargé de marketing digital"
    assert display_title("Growth Manager F/H/X - CDI") == "Growth Manager"
    assert display_title("Consultant SEA H/F CDI") == "Consultant SEA"
    assert display_title("Head of Growth") == "Head of Growth"


def test_role_title_strips_a_company_prefix_only():
    assert role_title("BETC Fullsix - Consultant CRM (H/F)", "BETC Fullsix") == "Consultant CRM (H/F)"
    assert role_title("SEO - Content Manager", "Shine") == "SEO - Content Manager"


def test_file_names_are_plain_and_hyphenated(cand):
    assert cand.file_stem == "Alex-Moreau"
    assert file_part("Société Générale") == "Societe-Generale"
    assert file_tag("L'Oréal Groupe") == "L-Oreal-Groupe"
    assert file_tag("   ") == "Entreprise"
    for name in (file_tag("Alan"), cand.file_stem):
        assert "ats" not in name.lower().split("-")


def test_language_detection():
    fr = ("Nous recherchons un chargé de marketing digital pour piloter nos campagnes. Vous serez en charge de la "
          "stratégie d'acquisition et vous travaillerez avec les équipes produit et ventes sur le développement de "
          "notre présence en ligne, dans une entreprise en forte croissance.")
    en = ("We are looking for a growth marketer to own our paid acquisition and lifecycle campaigns. You will work "
          "with the product and sales teams on the growth of our brand, and you will report to the head of marketing "
          "in a company that is scaling across Europe.")
    assert detect_lang(fr) == "fr"
    assert detect_lang(en) == "en"
    assert detect_lang("Growth Manager") is None  # too short to tell: the scorer's guess is used instead


def test_title_filter_keeps_marketing_roles_and_drops_the_rest(cand):
    ok = title_filter(cand.config)
    keep = ["Chargé de marketing digital (H/F)", "Growth Marketing Manager", "Consultant SEA H/F", "CRM Manager",
            "Head of paid", "Consultant SMA (H/F)", "Consultant Salesforce Marketing Cloud - F/H",
            "SEO/GEO Account Manager Confirmé/Senior F/H", "Community Developer - Unannounced Projects",
            "Social Media Manager", "Chargé(e) de recrutement international", "Traffic Manager",
            "Account Manager", "Sales Development Representative", "Chargé de partenariats sport (H/F)",
            "Chef de projet sponsoring", "Sports Marketing Manager", "Chef de projet événementiel", "Business Developer",
            "Fan Engagement Lead"]
    drop = ["Stage - Assistant marketing digital", "Alternance Chargé de communication", "Market Manager",
            "Key Account Manager", "Chef de projet informatique", "Téléconseiller", "Senior Software Engineer",
            "PREVENTEUR", "Projectionniste - animateur jeune public", "ADJOINT CHEF MAGASIN MATERIEL DE CAMPAGNE",
            "CHARGE DE PROJET EN CONDUITE D'OPERATIONS", "Directeur Marketing", "Contrôleur de gestion retail et digital",
            "Procurement Category Manager (Workplace and Marketing)",
            "Marketing Intern", "Product Manager CRM", "Fraud Analyst - French Market"]
    assert [t for t in keep if not ok(t)] == []
    assert [t for t in drop if ok(t)] == []
