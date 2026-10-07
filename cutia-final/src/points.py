"""
Credite și puncte bonus pentru studenți.

Punctele NU se salvează ca număr: se calculează mereu din ce a făcut
studentul (teme, idei, voturi) plus bonusurile date de trainer. Așa nu pot
fi „umflate” din browser și se corectează singure dacă trainerul schimbă
ceva (de exemplu anulează „Aleasă”).
"""

import os
import random
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

RULES = {
    "submission": 10,       # temă sau proiect predat
    "on_time": 5,           # predat înainte de termenul temei
    "reviewed": 20,         # trainerul a marcat „revizuit ✓” (sau punctele temei, dacă are)
    "idea": 5,              # idee pusă în cutie
    "vote": 2,              # fiecare vot primit de la colegi
    "chosen": 30,           # idee aleasă de trainer
    "question": 2,          # întrebare pusă (maxim QUESTIONS_PER_DAY pe zi)
    "showcase": 10,         # proiect arătat la Demo Day (maxim SHOWCASE_COUNTED)
    "spotlight": 25,        # proiectul săptămânii, ales de trainer
    "quest": 5,             # misiune săptămânală îndeplinită
}
SHOWCASE_COUNTED = 3
QUESTIONS_PER_DAY = 3

LEVELS = [  # (puncte minime, cheie de traducere)
    (0, "rookie"), (50, "apprentice"), (120, "crafter"),
    (220, "builder"), (350, "shipper"), (520, "wizard"),
]


# ---------------------------------------------------------------- serii și misiuni săptămânale
# Tot din activitatea reală: nimic nu se bifează din browser.

QUESTS = [  # (cheie, tip de activitate, câte trebuie în săptămână)
    ("ask", "question", 2), ("homework", "homework", 1), ("byte", "challenge", 2), ("lab", "prompt_lab", 3),
    ("live", "live", 1), ("idea", "idea", 1), ("showcase", "showcase", 1), ("doctor", "doctor", 1),
]
QUESTS_PER_WEEK = 4


def _tz():
    try:
        return ZoneInfo(os.environ.get("CUTIA_TZ", "Europe/Bucharest")) if ZoneInfo else timezone.utc
    except Exception:
        return timezone.utc


def local_day(iso: str) -> date:
    if len(iso) == 10:  # deja o zi (provocările lui Byte)
        return date.fromisoformat(iso)
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(_tz()).date()


def today() -> date:
    return datetime.now(_tz()).date()


def week_id(day: date) -> str:
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def quests_for(week: str) -> list:
    """Aceleași 4 misiuni pentru toată clasa într-o săptămână, altele săptămâna următoare."""
    return random.Random(week).sample(QUESTS, QUESTS_PER_WEEK)


def activity(db: dict) -> dict:
    """{student: [(tip, data ISO)]} din tot ce a făcut fiecare."""
    acts = defaultdict(list)
    for q in db.get("questions", []):
        acts[q["author_key"]].append(("question", q["created_at"]))
    for x in db.get("submissions", []):
        if x["kind"] != "other":
            acts[x["author_key"]].append(("homework", x["created_at"]))
    for p in db.get("proposals", []):
        acts[p["author_key"]].append(("idea", p["created_at"]))
    for x in db.get("showcase", []):
        acts[x["author_key"]].append(("showcase", x["created_at"]))
    for x in db.get("doctor", []):
        acts[x["author_key"]].append(("doctor", x["created_at"]))
    for key, days in db.get("challenges", {}).items():
        acts[key] += [("challenge", d) for d in days]
    for key, times in db.get("lab_log", {}).items():
        acts[key] += [("prompt_lab", t) for t in times]
    sessions = list(db.get("live_history", [])) + ([db["live"]] if db.get("live") else [])
    for live in sessions:
        for q in live.get("queue", []):
            acts[q["author_key"]].append(("live", q["created_at"]))
        for key, a in ((live.get("ticket") or {}).get("answers") or {}).items():
            acts[key].append(("live", a["at"]))
        for s in live.get("stuck_log", []):
            acts[s["key"]].append(("live", s["at"]))
    return acts


def quest_progress(acts: list, week: str) -> list:
    counts = defaultdict(int)
    for kind, at in acts:
        if week_id(local_day(at)) == week:
            counts[kind] += 1
    return [{"key": k, "kind": kind, "target": n, "progress": min(n, counts[kind]), "done": counts[kind] >= n}
            for k, kind, n in quests_for(week)]


def streaks(acts: list) -> dict:
    days = sorted({local_day(at) for _, at in acts})
    best = run = 0
    prev = None
    for d in days:
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        best, prev = max(best, run), d
    # Seria de acum: continuă dacă ai lucrat azi sau ieri
    current, d = 0, today()
    have = set(days)
    if d not in have:
        d -= timedelta(days=1)
    while d in have:
        current += 1
        d -= timedelta(days=1)
    return {"current": current, "best": best, "today": today() in have}


def level_for(total: int) -> dict:
    current, nxt = LEVELS[0], None
    for i, lvl in enumerate(LEVELS):
        if total >= lvl[0]:
            current = lvl
            nxt = LEVELS[i + 1] if i + 1 < len(LEVELS) else None
    return {
        "index": LEVELS.index(current) + 1,
        "key": current[1],
        "min": current[0],
        "next_min": nxt[0] if nxt else None,
        "next_key": nxt[1] if nxt else None,
    }


def compute(db: dict) -> dict:
    """Întoarce {student_key: {"total", "events": [...]}} pentru toți studenții."""
    out = defaultdict(lambda: {"total": 0, "events": []})
    assignments = {a["id"]: a for a in db.get("assignments", [])}

    def add(key, kind, pts, ref=None, at=None):
        if pts:
            out[key]["total"] += pts
            out[key]["events"].append({"kind": kind, "points": pts, "ref": ref, "at": at})

    # Teme & proiecte: o singură predare punctată per temă anunțată
    counted_assignments = set()
    for sub in sorted(db.get("submissions", []), key=lambda x: x["created_at"]):
        if sub["kind"] == "other":
            continue
        key, aid = sub["author_key"], sub.get("assignment_id")
        if aid is not None:
            if (key, aid) in counted_assignments:
                continue
            counted_assignments.add((key, aid))
        add(key, "submission", RULES["submission"], sub["title"], sub["created_at"])
        a = assignments.get(aid)
        if a and a.get("due_at") and sub["created_at"] <= a["due_at"]:
            add(key, "on_time", RULES["on_time"], sub["title"], sub["created_at"])
        if sub.get("status") == "reviewed":
            pts = a.get("points", RULES["reviewed"]) if a else RULES["reviewed"]
            add(key, "reviewed", pts, sub["title"], sub.get("reviewed_at"))

    for p in db.get("proposals", []):
        key = p["author_key"]
        # O idee retrasă nu mai aduce puncte pentru idee și voturi (dar „aleasă” rămâne)
        if p.get("status") != "withdrawn":
            add(key, "idea", RULES["idea"], p["title"], p["created_at"])
            add(key, "vote", RULES["vote"] * len([v for v in p["voters"] if v != key]), p["title"], p["created_at"])
        if p.get("chosen"):
            add(key, "chosen", RULES["chosen"], p["title"], p["created_at"])

    per_day = defaultdict(int)
    for q in db.get("questions", []):
        day = (q["author_key"], q["created_at"][:10])
        per_day[day] += 1
        if per_day[day] <= QUESTIONS_PER_DAY:
            add(q["author_key"], "question", RULES["question"], q["text"][:60], q["created_at"])

    shown = defaultdict(int)
    for item in sorted(db.get("showcase", []), key=lambda x: x["created_at"]):
        shown[item["author_key"]] += 1
        if shown[item["author_key"]] <= SHOWCASE_COUNTED:
            add(item["author_key"], "showcase", RULES["showcase"], item["title"], item["created_at"])
        if item.get("spotlight"):
            add(item["author_key"], "spotlight", RULES["spotlight"], item["title"], item.get("spotlight_at") or item["created_at"])

    for key, acts in activity(db).items():
        for week in sorted({week_id(local_day(at)) for _, at in acts}):
            for q in quest_progress(acts, week):
                if q["done"]:
                    last = max(at for kind, at in acts if kind == q["kind"] and week_id(local_day(at)) == week)
                    add(key, "quest", RULES["quest"], q["key"], last)

    for b in db.get("bonuses", []):
        add(b["student_key"], "bonus", b["points"], b["reason"], b["created_at"])

    return out


def badges(key: str, db: dict, total: int) -> list:
    subs = [x for x in db.get("submissions", []) if x["author_key"] == key and x["kind"] != "other"]
    ideas = [p for p in db.get("proposals", []) if p["author_key"] == key and p.get("status") != "withdrawn"]
    votes = sum(len([v for v in p["voters"] if v != key]) for p in ideas)
    questions = [q for q in db.get("questions", []) if q["author_key"] == key]
    checks = {
        "first_question": len(questions) >= 1,
        "first_homework": len(subs) >= 1,
        "five_homework": len(subs) >= 5,
        "first_idea": len(ideas) >= 1,
        "crowd_favorite": votes >= 5,
        "chosen": any(p.get("chosen") for p in db.get("proposals", []) if p["author_key"] == key),
        "perfectionist": any(x.get("status") == "reviewed" and len(x.get("checklist", [])) == 6 for x in subs),
        "century": total >= 100,
        "demo_day": any(x["author_key"] == key for x in db.get("showcase", [])),
        "streak_7": streaks(activity(db).get(key, []))["best"] >= 7,
        "quest_master": any(all(q["done"] for q in quest_progress(activity(db).get(key, []), w))
                            for w in {week_id(local_day(at)) for _, at in activity(db).get(key, [])}),
    }
    return [k for k, ok in checks.items() if ok]
