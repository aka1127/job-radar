"""The languages CVs and letters can be written in: section titles, months, the word for "present", the date line
of a letter, and a light detector for the language of a posting. Adding a language is one entry in each table;
a posting in any other language gets an English pack (or the candidate's first CV language)."""
import re
from datetime import date

NAMES = {"en": "English", "fr": "French", "es": "Spanish", "de": "German", "it": "Italian", "pt": "Portuguese",
         "nl": "Dutch"}

LABELS = {
    "en": dict(profile="Profile", skills="Key skills", experience="Professional experience", education="Education",
               certifications="Certifications", languages="Languages", achievements="Achievements & involvement",
               projects="Projects & involvement", letter="Cover letter", subject="Application for the position of",
               letter_file="Cover-Letter"),
    "fr": dict(profile="Profil", skills="Compétences clés", experience="Expérience professionnelle", education="Formation",
               certifications="Certifications", languages="Langues", achievements="Distinctions & engagements",
               projects="Projets & engagements", letter="Lettre de motivation", subject="Objet : Candidature au poste de",
               letter_file="Lettre"),
    "es": dict(profile="Perfil", skills="Competencias clave", experience="Experiencia profesional", education="Formación",
               certifications="Certificaciones", languages="Idiomas", achievements="Logros y compromisos",
               projects="Proyectos y compromisos", letter="Carta de presentación",
               subject="Asunto: Candidatura al puesto de", letter_file="Carta"),
    "de": dict(profile="Profil", skills="Kernkompetenzen", experience="Berufserfahrung", education="Ausbildung",
               certifications="Zertifikate", languages="Sprachen", achievements="Auszeichnungen & Engagement",
               projects="Projekte & Engagement", letter="Anschreiben", subject="Betreff: Bewerbung als",
               letter_file="Anschreiben"),
    "it": dict(profile="Profilo", skills="Competenze chiave", experience="Esperienza professionale", education="Formazione",
               certifications="Certificazioni", languages="Lingue", achievements="Riconoscimenti e impegni",
               projects="Progetti e impegni", letter="Lettera di presentazione",
               subject="Oggetto: Candidatura per la posizione di", letter_file="Lettera"),
    "pt": dict(profile="Perfil", skills="Competências-chave", experience="Experiência profissional", education="Formação",
               certifications="Certificações", languages="Idiomas", achievements="Conquistas e envolvimento",
               projects="Projetos e envolvimento", letter="Carta de apresentação", subject="Assunto: Candidatura à vaga de",
               letter_file="Carta"),
    "nl": dict(profile="Profiel", skills="Kerncompetenties", experience="Werkervaring", education="Opleiding",
               certifications="Certificaten", languages="Talen", achievements="Prestaties & betrokkenheid",
               projects="Projecten & betrokkenheid", letter="Motivatiebrief", subject="Betreft: Sollicitatie als",
               letter_file="Motivatiebrief"),
}

_EN_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
# Short months as CVs write them, from the profile's English "Oct 2024 - Present".
MONTHS = {lang: dict(zip(_EN_MONTHS, names.split())) for lang, names in {
    "fr": "janv. févr. mars avr. mai juin juil. août sept. oct. nov. déc.",
    "es": "ene. feb. mar. abr. may. jun. jul. ago. sept. oct. nov. dic.",
    "de": "Jan. Feb. März Apr. Mai Juni Juli Aug. Sept. Okt. Nov. Dez.",
    "it": "gen. feb. mar. apr. mag. giu. lug. ago. set. ott. nov. dic.",
    "pt": "jan. fev. mar. abr. mai. jun. jul. ago. set. out. nov. dez.",
    "nl": "jan. feb. mrt. apr. mei jun. jul. aug. sep. okt. nov. dec.",
}.items()}
PRESENT = {"en": "Present", "fr": "aujourd'hui", "es": "actualidad", "de": "heute", "it": "oggi", "pt": "atual",
           "nl": "heden"}
LONG_MONTHS = {
    "en": "January February March April May June July August September October November December",
    "fr": "janvier février mars avril mai juin juillet août septembre octobre novembre décembre",
    "es": "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre",
    "de": "Januar Februar März April Mai Juni Juli August September Oktober November Dezember",
    "it": "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre",
    "pt": "janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro",
    "nl": "januari februari maart april mei juni juli augustus september oktober november december",
}
DATE_LINE = {"en": "{city}, {month} {day}, {year}", "fr": "{city}, le {day} {month} {year}",
             "es": "{city}, {day} de {month} de {year}", "de": "{city}, {day}. {month} {year}",
             "it": "{city}, {day} {month} {year}", "pt": "{city}, {day} de {month} de {year}",
             "nl": "{city}, {day} {month} {year}"}

STOPWORDS = {
    "en": "the and you we for with our to of is are your will be this that as on who what about into from have an at",
    "fr": "le la les des du et vous nous pour avec une est sur dans au aux votre notre nos vos sont qui que ou chez "
          "ainsi mais être",
    "es": "el la los las del y para con una es en su sus nuestro nuestra somos que como por más tu usted este esta "
          "estamos buscamos",
    "de": "der die das und für mit ein eine ist wir sie ihr ihre unser unsere bei von zu im auf den dem des oder "
          "werden suchen",
    "it": "il lo la gli le del della e per con una è siamo che come nel nella sono tu tuo tua nostro nostra cerchiamo "
          "degli",
    "pt": "o os as do da dos das e para com uma é em seu sua nosso nossa somos que como por mais você estamos "
          "procuramos",
    "nl": "de het een en van voor met is zijn wij jij je jouw onze ons bij op aan te dat die wordt zoeken",
}
_STOP = {lang: set(words.split()) for lang, words in STOPWORDS.items()}


def detect(text: str) -> str | None:
    """The language of a posting by common-word counts; None when the text is too short to tell."""
    words = re.findall(r"[a-zàâäçéèêëîïôöûùüÿœñßãõ]+", (text or "").lower())
    counts = {lang: sum(w in stop for w in words) for lang, stop in _STOP.items()}
    best = max(counts, key=counts.get)
    return best if sum(counts.values()) >= 15 and counts[best] >= 8 else None


def output_language(posting_lang: str | None, cv_languages: list[str]) -> str:
    """The pack is written in the posting's language when the candidate has a CV in it, else in English when they
    have one, else in their first CV language."""
    langs = [l for l in cv_languages if l in LABELS] or ["en"]
    if posting_lang in langs:
        return posting_lang
    return "en" if "en" in langs else langs[0]


def local_dates(dates: str, lang: str) -> str:
    """'Oct 2024 - Present' in the CV's language: 'oct. 2024 - aujourd'hui', 'Okt. 2024 - heute'."""
    months = MONTHS.get(lang)
    if months:
        dates = re.sub(r"\b(" + "|".join(months) + r")\b", lambda m: months[m.group(1)], dates)
    return dates.replace("Present", PRESENT.get(lang, "Present"))


def date_line(city: str, lang: str, today: date | None = None) -> str:
    today = today or date.today()
    month = LONG_MONTHS.get(lang, LONG_MONTHS["en"]).split()[today.month - 1]
    return DATE_LINE.get(lang, DATE_LINE["en"]).format(city=city, day=today.day, month=month, year=today.year)


def field(entry: dict, key: str, lang: str, default: str = "") -> str:
    """A profile field in the CV's language: title_de, else title_en, else title. Profiles hold the languages the
    person writes their CVs in; anything missing falls back to English."""
    return entry.get(f"{key}_{lang}") or entry.get(f"{key}_en") or entry.get(key) or default
