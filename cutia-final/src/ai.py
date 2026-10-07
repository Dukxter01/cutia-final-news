"""
Modulul AI al Cutiei Clasei.

1. Propuneri: retușează o propunere (titlu, ce face aplicația, cine o
   folosește), arată ce a înțeles și cere detalii DOAR unde lipsesc
   (maxim 3 întrebări). Fără cheie API, cade pe un mod local simplu.
2. Întrebări: un răspuns rapid de tip tutor de vibe coding, marcat clar ca
   „AI”. Răspunsul oficial rămâne cel al trainerului. Doar cu Claude.

Apelul către Claude se face doar pe server; cheia stă în variabile de mediu
(sau în .env, ignorat de git) și nu ajunge niciodată în browser.
"""

import json
import os
import re

MODEL = os.environ.get("CUTIA_MODEL", "claude-opus-5-5")

LANGS = ("ro", "en", "fr", "it", "es", "de")
LANGUAGE_NAME = {"ro": "Romanian", "en": "English", "fr": "French", "it": "Italian", "es": "Spanish", "de": "German"}

FIELDS = ("title", "description", "audience")

# Pragul sub care considerăm un câmp "lipsă" în modul local
MIN_LEN = {"title": 3, "description": 25, "audience": 4}

MAX_QUESTIONS = 3

# Ce verifică AI-ul la fiecare propunere (din fișa trainerului).
# Răspunsurile la problem/features/data/size se adaugă la descriere.
CHECKS = ("problem", "features", "data", "size")

REFINE_PROMPT = """Ești asistentul din „Cutia Clasei", aplicația unei clase de \
vibe coding (programare cu AI), în care studenții propun proiecte pentru ora \
următoare. Primești o propunere cu trei câmpuri obligatorii: titlu, ce face \
aplicația (description) și cine o folosește (audience).

Nu decizi în locul studentului: îi arăți ce ai înțeles, îi spui ce lipsește, \
iar el alege ce versiune trimite.

Sarcina ta:
1. În "understood" rezumă în 1-2 propoziții ce ai înțeles: ce problemă rezolvă \
aplicația, pentru cine și ce face.
2. Retușează cele trei câmpuri: corectează gramatica și diacriticele, fă textul \
clar și concis, păstrează ideea și vocea studentului. Nu inventa funcții sau detalii noi.
3. Verifică propunerea și, DOAR pentru ce lipsește sau e prea vag, adaugă în \
"missing" o întrebare scurtă și concretă:
   - title: lipsește titlul? („Cum se numește aplicația?")
   - audience: nu e clar cine o folosește? („Cine o va folosi?")
   - problem: nu e clară problema? („Ce problemă rezolvă aplicația și pentru cine?")
   - features: nu sunt clare funcțiile? („Care sunt cele 3 lucruri pe care trebuie să le facă sigur?")
   - data: nu e clar de unde vin datele? („De unde vin datele: le introduce \
utilizatorul sau vin din alt serviciu?")
   - size: pare prea mare pentru o oră? („Se poate construi într-o oră? Dacă nu, \
ce parte facem prima?")
   Pune cel mult 3 întrebări, cele mai importante primele. Dacă un aspect e \
suficient de clar, NU întreba despre el. Dacă totul e clar, "missing" e o listă goală.
4. Dacă un câmp lipsește complet, lasă-l gol în varianta retușată.
5. În "notes" scrie o singură propoziție despre ce ai schimbat în text."""

TUTOR_PROMPT = """You are the teaching assistant of a beginner "vibe coding" class: \
students learn to build apps by working with AI tools (Claude, Claude Code, \
artifacts, GitHub, Supabase, deploy platforms). A student asked the trainer a \
question; you give a quick first answer while they wait for the trainer.

How to answer:
- Be short and practical: at most ~150 words. Plain language, no jargon without \
a one-line explanation.
- When it helps, include ONE example prompt the student can paste into Claude, \
in a fenced code block.
- Prefer teaching the habit (how to ask the AI, how to check its work) over \
giving a finished solution.
- Security first: API keys stay on the server / in environment variables, never \
in the browser or on GitHub; access rules are enforced on the server or in the \
database (e.g. Row Level Security), not only in the UI.
- If you are not sure, say so. Never invent product features. End with one line \
suggesting what to clarify with the trainer if anything is uncertain.
- Use simple Markdown only (short paragraphs, bullet lists, code blocks)."""

REFINE_SCHEMA = {
    "type": "object",
    "properties": {
        "understood": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "audience": {"type": "string"},
        "missing": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": [*FIELDS, *CHECKS]},
                    "question": {"type": "string"},
                },
                "required": ["field", "question"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["understood", "title", "description", "audience", "missing", "notes"],
    "additionalProperties": False,
}

LOCAL_TEXT = {
    "ro": {
        "title": "Cum s-ar numi aplicația? Alege un nume scurt.",
        "description": "Descrie pe scurt 2-3 lucruri pe care le poate face un utilizator.",
        "audience": "Pentru cine e aplicația? (de ex. studenții, trainerul, părinții)",
        "named": "Propui „{}”.",
        "idea": "Ideea: {}",
        "users": "O folosesc: {}.",
        "notes": "Retușare locală (fără AI): am curățat spațiile, majusculele și punctuația.",
    },
    "en": {
        "title": "What would you call the app? Pick a short name.",
        "description": "Briefly describe 2-3 things a user can do in it.",
        "audience": "Who is the app for? (e.g. students, the trainer, parents)",
        "named": "You're proposing “{}”.",
        "idea": "The idea: {}",
        "users": "Used by: {}.",
        "notes": "Local touch-up (no AI): cleaned up spacing, capitalisation and punctuation.",
    },
    "fr": {
        "title": "Comment s'appellerait l'application ? Choisis un nom court.",
        "description": "Décris en bref 2-3 choses qu'un utilisateur peut y faire.",
        "audience": "À qui s'adresse l'application ? (ex. les étudiants, le formateur, les parents)",
        "named": "Tu proposes « {} ».",
        "idea": "L'idée : {}",
        "users": "Utilisée par : {}.",
        "notes": "Retouche locale (sans IA) : espaces, majuscules et ponctuation nettoyés.",
    },
    "it": {
        "title": "Come si chiamerebbe l'app? Scegli un nome breve.",
        "description": "Descrivi in breve 2-3 cose che un utente può fare.",
        "audience": "Per chi è l'app? (es. gli studenti, il trainer, i genitori)",
        "named": "Proponi «{}».",
        "idea": "L'idea: {}",
        "users": "La usano: {}.",
        "notes": "Ritocco locale (senza IA): sistemati spazi, maiuscole e punteggiatura.",
    },
    "es": {
        "title": "¿Cómo se llamaría la app? Elige un nombre corto.",
        "description": "Describe en breve 2-3 cosas que un usuario puede hacer.",
        "audience": "¿Para quién es la app? (p. ej. estudiantes, el formador, los padres)",
        "named": "Propones «{}».",
        "idea": "La idea: {}",
        "users": "La usan: {}.",
        "notes": "Retoque local (sin IA): espacios, mayúsculas y puntuación corregidos.",
    },
    "de": {
        "title": "Wie würde die App heißen? Wähle einen kurzen Namen.",
        "description": "Beschreibe kurz 2-3 Dinge, die man darin tun kann.",
        "audience": "Für wen ist die App? (z. B. Studierende, Trainer, Eltern)",
        "named": "Du schlägst „{}“ vor.",
        "idea": "Die Idee: {}",
        "users": "Genutzt von: {}.",
        "notes": "Lokale Überarbeitung (ohne KI): Leerzeichen, Großschreibung und Satzzeichen bereinigt.",
    },
}


def lang_or_default(lang: str) -> str:
    return lang if lang in LANGS else "ro"


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return ""
    return text[0].upper() + text[1:]


def _sentence(text: str) -> str:
    text = _clean(text)
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _lower_first(text: str) -> str:
    return text[0].lower() + text[1:] if text else text


def _understood_local(p: dict, t: dict) -> str:
    """Rezumat simplu „ce am înțeles”, compus din câmpurile completate."""
    parts = []
    if p["title"]:
        parts.append(t["named"].format(p["title"]))
    if p["description"]:
        parts.append(t["idea"].format(p["description"]))
    if p["audience"]:
        parts.append(t["users"].format(_lower_first(p["audience"])))
    return " ".join(parts)


def refine_local(title: str, description: str, audience: str, lang: str = "ro") -> dict:
    """Retușare simplă fără AI: curăță spațiile, majuscule, punctuație."""
    t = LOCAL_TEXT[lang_or_default(lang)]
    raw = {"title": title, "description": description, "audience": audience}
    refined = {
        "title": _clean(title).rstrip("."),
        "description": _sentence(description),
        "audience": _clean(audience).rstrip("."),
    }
    missing = [
        {"field": f, "question": t[f]}
        for f in FIELDS
        if len((raw[f] or "").strip()) < MIN_LEN[f]
    ]
    for item in missing:
        if not (raw[item["field"]] or "").strip():
            refined[item["field"]] = ""
    return {
        "understood": _understood_local(refined, t),
        **refined,
        "missing": missing[:MAX_QUESTIONS],
        "notes": t["notes"],
        "engine": "local",
    }


def available() -> bool:
    """True dacă modulul AI poate folosi Claude (există credențiale)."""
    mode = os.environ.get("CUTIA_AI", "auto")
    if mode == "off":
        return False
    has_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    return mode == "on" or bool(has_key)


def _client():
    if not available():
        return None
    try:
        import anthropic
        return anthropic.Anthropic()
    except Exception:
        return None


def language_line(lang: str) -> str:
    return f"\n\nWrite every piece of text in your answer in {LANGUAGE_NAME[lang_or_default(lang)]}."


def refine(title: str, description: str, audience: str, lang: str = "ro") -> dict:
    """Retușează propunerea cu Claude; dacă nu se poate, folosește modul local."""
    client = _client()
    if client is None:
        return refine_local(title, description, audience, lang)

    import anthropic

    payload = json.dumps(
        {"title": title, "description": description, "audience": audience},
        ensure_ascii=False,
    )
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4000,
            system=REFINE_PROMPT + language_line(lang),
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": REFINE_SCHEMA},
            },
            messages=[{"role": "user", "content": f"Propunerea / The proposal:\n{payload}"}],
        )
        if response.stop_reason in ("refusal", "max_tokens"):
            return refine_local(title, description, audience, lang)
        text = next(b.text for b in response.content if b.type == "text")
        data = json.loads(text)
    except (anthropic.APIError, StopIteration, json.JSONDecodeError, TypeError):
        return refine_local(title, description, audience, lang)

    data["missing"] = [
        m for m in data.get("missing", []) if m.get("field") in (*FIELDS, *CHECKS)
    ][:MAX_QUESTIONS]
    data["engine"] = "claude"
    return data


def answer_question(text: str, topic: str, lang: str = "ro"):
    """Răspuns rapid de la tutorul AI. Întoarce None dacă AI-ul nu e disponibil."""
    client = _client()
    if client is None:
        return None

    import anthropic

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=TUTOR_PROMPT + language_line(lang),
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": f"Topic: {topic}\n\nQuestion:\n{text}"}],
        )
    except anthropic.APIError:
        return None
    if response.stop_reason == "refusal":
        return None
    answer = "".join(b.text for b in response.content if b.type == "text").strip()
    return answer or None
