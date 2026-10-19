import os
import tempfile

os.environ["CUTIA_PERSIST"] = "0"
os.environ["CUTIA_AI"] = "off"
os.environ["TRAINER_CODE"] = "cod-trainer-test"
os.environ["TRAINER_EMAILS"] = "radu@test.ro"
os.environ.pop("SUPABASE_URL", None)
os.environ.pop("SUPABASE_SECRET_KEY", None)
os.environ.pop("VERCEL", None)
os.environ["CUTIA_UPLOADS"] = tempfile.mkdtemp()

import base64
import json as _json

import httpx
import pytest
from fastapi.testclient import TestClient

from src import app as app_module

client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def reset_db():
    app_module.db.update({
        "users": {}, "revoked": {}, "prefs": {}, "drafts": [], "questions": [], "proposals": [], "submissions": [],
        "messages": [], "assignments": [], "announcements": [], "bonuses": [], "next_id": 1,
        "doctor": [], "hall": [], "live": None, "live_history": [], "showcase": [], "faq": [], "challenges": {}, "push": {}, "kickstarts": {}, "lab_log": {}, "recaps": {}, "digests": [], "refine_log": {},
    })
    app_module._failed.clear()
    app_module._cooldowns.clear()
    app_module._remote.update(versions={}, hashes={})


TRAINER = {"name": "Radu", "email": "radu@test.ro", "password": "parola-test", "trainer_code": "cod-trainer-test"}


def auth(r):
    assert r.status_code in (200, 201), r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def trainer_headers():
    if "radu@test.ro" not in app_module.db["users"]:
        return auth(client.post("/api/setup", json=TRAINER))
    return auth(client.post("/api/login", json={"login": "radu@test.ro", "password": "parola-test"}))


def login(name, role="student", password="parola-test"):
    """Radu = trainerul (email + parolă). Studenții: contul îl face trainerul (utilizator = numele mic)."""
    if role == "trainer":
        return trainer_headers()
    username = name.lower().replace(" ", ".")
    if username not in app_module.db["users"]:
        r = client.post("/api/students", json={"username": username, "name": name, "password": password}, headers=trainer_headers())
        assert r.status_code == 201, r.text
    r = client.post("/api/login", json={"login": username, "password": password})
    assert r.json()["role"] == role
    return auth(r)


def test_trainer_setup_needs_code_and_listed_email():
    base = {**TRAINER}
    assert client.get("/api/config").json()["needs_setup"] is True
    assert client.post("/api/setup", json={**base, "trainer_code": "gresit"}).status_code == 403
    assert client.post("/api/setup", json={**base, "email": "altcineva@test.ro"}).status_code == 403
    assert client.post("/api/setup", json={**base, "password": "scurt"}).status_code == 400
    r = client.post("/api/setup", json=base)
    assert r.status_code == 201 and r.json()["role"] == "trainer"
    assert client.post("/api/setup", json=base).status_code == 409
    assert client.get("/api/config").json()["needs_setup"] is False
    # Trainerul intră cu emailul (litere mari / spații nu contează)
    assert client.post("/api/login", json={"login": " Radu@Test.ro ", "password": "parola-test"}).json()["role"] == "trainer"


def test_setup_is_off_without_trainer_code(monkeypatch):
    monkeypatch.setattr(app_module, "TRAINER_CODE", "")
    assert client.post("/api/setup", json=TRAINER).status_code == 403
    assert client.get("/api/config").json()["setup_enabled"] is False


def test_setup_code_cannot_be_brute_forced():
    for _ in range(5):
        assert client.post("/api/setup", json={**TRAINER, "trainer_code": "ghicit-1"}).status_code == 403
    assert client.post("/api/setup", json=TRAINER).status_code == 429


def test_no_oauth_signup():
    for path in ("/api/auth/google", "/api/auth/supabase"):
        assert client.post(path, json={"name": "X", "email": "x@x.ro", "password": "parola-buna"}).status_code in (404, 405)


def test_students_register_with_email_and_password():
    body = {"name": "Ana Pop", "email": " Ana@Test.ro ", "password": "parola-buna"}
    r = client.post("/api/register", json=body)
    assert r.status_code == 201 and r.json()["role"] == "student"
    assert client.post("/api/register", json=body).status_code == 409
    assert client.post("/api/register", json={**body, "email": "nu-e-email"}).status_code == 400
    assert client.post("/api/register", json={**body, "email": "b@test.ro", "password": "scurt"}).status_code == 400
    r = client.post("/api/login", json={"login": "ana@test.ro", "password": "parola-buna"})
    assert r.status_code == 200 and r.json()["role"] == "student"
    me = client.get("/api/me", headers=auth(r)).json()
    assert me["role"] == "student" and me["email"] == "ana@test.ro"
    # Un student nu poate face nimic de trainer
    assert client.get("/api/students", headers=auth(r)).status_code == 403


def test_only_trainer_email_becomes_trainer_and_needs_code():
    base = {"name": "Radu", "email": "Radu@test.ro", "password": "parola-test"}
    assert client.post("/api/register", json=base).status_code == 428
    assert client.post("/api/register", json={**base, "trainer_code": "gresit"}).status_code == 403
    r = client.post("/api/register", json={**base, "trainer_code": "cod-trainer-test"})
    assert r.status_code == 201 and r.json()["role"] == "trainer"
    assert client.post("/api/register", json={**base, "trainer_code": "cod-trainer-test"}).status_code == 409
    assert client.get("/api/config").json()["needs_setup"] is False


def test_trainer_email_without_code_only_while_no_trainer(monkeypatch):
    monkeypatch.setattr(app_module, "TRAINER_CODE", "")
    base = {"name": "Radu", "email": "radu@test.ro", "password": "parola-test"}
    assert client.post("/api/register", json=base).json()["role"] == "trainer"
    app_module.db["users"].pop("radu@test.ro")
    app_module.db["users"]["alt@test.ro"] = {"name": "X", "role": "trainer", "email": "alt@test.ro", "gen": 0}
    assert client.post("/api/register", json=base).status_code == 409


def test_default_trainer_email_is_radu():
    assert app_module.DEFAULT_TRAINER_EMAIL == "stoichin.radu23@gmail.com"


def test_registered_students_dont_see_each_others_questions():
    a = auth(client.post("/api/register", json={"name": "A", "email": "a@test.ro", "password": "parola-buna"}))
    b = auth(client.post("/api/register", json={"name": "B", "email": "b@test.ro", "password": "parola-buna"}))
    assert client.post("/api/questions", json={"text": "Intrebarea lui A?"}, headers=a).status_code in (200, 201)
    assert len(client.get("/api/questions", headers=a).json()) == 1
    assert client.get("/api/questions", headers=b).json() == []


def test_registration_can_be_closed(monkeypatch):
    monkeypatch.setattr(app_module, "REGISTRATION_OPEN", False)
    assert client.post("/api/register", json={"name": "A", "email": "a@test.ro", "password": "parola-buna"}).status_code == 403
    assert client.get("/api/config").json()["registration"] is False


def test_only_trainer_creates_students_with_valid_usernames():
    ht, ana = login("Radu", "trainer"), login("Ana")
    body = {"username": "mihai", "name": "Mihai Ionescu", "password": "parola-mihai"}
    assert client.post("/api/students", json=body, headers=ana).status_code == 403
    assert client.post("/api/students", json=body).status_code == 401
    for bad in ("ab", "cu spatiu", "ana@x.ro", "-minus", "x" * 40):
        assert client.post("/api/students", json={**body, "username": bad}, headers=ht).status_code in (400, 422), bad
    assert client.post("/api/students", json={**body, "password": "scurt"}, headers=ht).status_code == 400
    r = client.post("/api/students", json={**body, "username": "Mihai"}, headers=ht)
    assert r.status_code == 201 and r.json() == {"key": "mihai", "username": "mihai", "name": "Mihai Ionescu"}
    assert client.post("/api/students", json=body, headers=ht).status_code == 409
    assert client.post("/api/students", json={**body, "username": "radu@test.ro"}, headers=ht).status_code == 400
    r = client.post("/api/login", json={"login": "MIHAI", "password": "parola-mihai"})
    assert r.json() == {**r.json(), "name": "Mihai Ionescu", "role": "student"}
    me = client.get("/api/me", headers=auth(r)).json()
    assert me["login"] == "mihai" and me["email"] is None
    assert {s["key"] for s in client.get("/api/students", headers=ht).json()} == {"ana", "mihai"}


def test_trainer_renames_sets_password_and_deletes_student():
    ht, ana = login("Radu", "trainer"), login("Ana")
    assert client.patch("/api/students/ana", json={"name": "Ana P."}, headers=ana).status_code == 403
    assert client.patch("/api/students/radu@test.ro", json={"name": "X"}, headers=ht).status_code == 404
    assert client.patch("/api/students/ana", json={"name": "Ana P."}, headers=ht).json()["name"] == "Ana P."
    assert client.get("/api/me", headers=ana).json()["name"] == "Ana P."      # numele nou apare imediat
    assert client.patch("/api/students/ana", json={"password": "scurt"}, headers=ht).status_code == 400
    assert client.patch("/api/students/ana", json={"password": "parola-noua-ana"}, headers=ht).status_code == 200
    assert client.get("/api/me", headers=ana).status_code == 401              # sesiunile vechi s-au închis
    ana = auth(client.post("/api/login", json={"login": "ana", "password": "parola-noua-ana"}))
    client.post("/api/questions", json={"text": "Întrebarea Anei"}, headers=ana)
    assert client.delete("/api/students/ana", headers=ana).status_code == 403
    assert client.delete("/api/students/ana", headers=ht).json() == {"ok": True}
    assert client.get("/api/me", headers=ana).status_code == 401
    assert client.post("/api/login", json={"login": "ana", "password": "parola-noua-ana"}).status_code == 401
    assert client.get("/api/questions", headers=ht).json()[0]["text"] == "Întrebarea Anei"   # ce a scris rămâne


def test_login_lockout_after_failed_attempts():
    login("Ana")
    for _ in range(5):
        assert client.post("/api/login", json={"login": "ana", "password": "gresit!!"}).status_code == 401
    r = client.post("/api/login", json={"login": "ana", "password": "parola-test"})
    assert r.status_code == 429


def test_wrong_username_and_wrong_password_look_the_same():
    login("Ana")
    a = client.post("/api/login", json={"login": "nimeni", "password": "orice-parola"}).json()
    b = client.post("/api/login", json={"login": "ana", "password": "orice-parola"}).json()
    assert a == b


def test_forged_or_tampered_tokens_are_rejected():
    ana = login("Ana")
    token = ana["Authorization"].split()[1]
    payload, sig = token.split(".")
    import base64, json as js
    data = js.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    forged = base64.urlsafe_b64encode(js.dumps({**data, "k": "radu@test.ro"}).encode()).rstrip(b"=").decode()
    login("Radu", "trainer")
    for bad in (f"{forged}.{sig}", token + "x", "nu-e-token", ""):
        assert client.get("/api/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_trainer_can_reset_a_student_password():
    ana = login("Ana")
    trainer = login("Radu", "trainer")
    assert client.post("/api/students/ana/reset-password", headers=ana).status_code == 403
    temp = client.post("/api/students/ana/reset-password", headers=trainer).json()["temporary_password"]
    assert client.get("/api/me", headers=ana).status_code == 401  # sesiunea veche s-a închis
    assert client.post("/api/login", json={"login": "ana", "password": temp}).status_code == 200


def test_questions_visible_only_to_author_and_trainer():
    ana, bob = login("Ana"), login("Bob")
    trainer = login("Radu", "trainer")

    r = client.post("/api/questions", json={"text": "Ce e un API?"}, headers=ana)
    assert r.status_code == 201
    qid = r.json()["id"]

    assert len(client.get("/api/questions", headers=ana).json()) == 1
    assert client.get("/api/questions", headers=bob).json() == []
    assert len(client.get("/api/questions", headers=trainer).json()) == 1

    # Doar trainerul răspunde
    assert client.post(f"/api/questions/{qid}/answer", json={"text": "x"}, headers=bob).status_code == 403
    r = client.post(f"/api/questions/{qid}/answer", json={"text": "O interfață."}, headers=trainer)
    assert r.status_code == 200
    assert client.get("/api/questions", headers=ana).json()[0]["answer"] == "O interfață."


def test_anonymous_question_hides_name_from_trainer():
    ana = login("Ana")
    trainer = login("Radu", "trainer")
    client.post("/api/questions", json={"text": "Întrebare", "anonymous": True}, headers=ana)
    q = client.get("/api/questions", headers=trainer).json()[0]
    assert q["author"] == "Anonim"
    assert "author_key" not in q


def test_refine_asks_only_for_missing_fields():
    ana = login("Ana")
    r = client.post("/api/proposals/refine", json={
        "title": "  calendarul clasei ",
        "description": "arata   termenele temelor si orele de curs intr-un singur loc",
        "audience": "",
    }, headers=ana)
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "Calendarul clasei"
    assert data["description"].endswith(".")
    assert [m["field"] for m in data["missing"]] == ["audience"]


def test_submit_requires_approval_and_fields():
    ana = login("Ana")
    body = {"title": "Calendar", "description": "Arată termenele.", "audience": "Studenții"}
    assert client.post("/api/proposals", json=body, headers=ana).status_code == 400
    assert client.post("/api/proposals", json={**body, "audience": "", "approved": True}, headers=ana).status_code == 400
    assert client.post("/api/proposals", json={**body, "approved": True}, headers=ana).status_code == 201


def test_trainer_chooses_and_students_vote():
    ana, bob = login("Ana"), login("Bob")
    trainer = login("Radu", "trainer")
    body = {"title": "Calendar", "description": "Arată termenele.", "audience": "Studenții", "approved": True}
    pid = client.post("/api/proposals", json=body, headers=ana).json()["id"]

    assert client.post(f"/api/proposals/{pid}/choose", headers=ana).status_code == 403
    assert client.post(f"/api/proposals/{pid}/choose", headers=trainer).json()["chosen"] is True

    assert client.post(f"/api/proposals/{pid}/vote", headers=bob).json()["votes"] == 1
    assert client.post(f"/api/proposals/{pid}/vote", headers=bob).json()["votes"] == 0
    assert client.post(f"/api/proposals/{pid}/vote", headers=trainer).status_code == 403

    listed = client.get("/api/proposals", headers=trainer).json()
    assert listed[0]["chosen"] is True and "voters" not in listed[0]


def test_requires_login():
    assert client.get("/api/questions").status_code == 401


def test_student_b_cannot_log_in_as_student_a():
    ana = login("Ana", password="parola-ana1")
    client.post("/api/questions", json={"text": "Întrebarea Anei"}, headers=ana)

    # Studentul B încearcă să intre pe contul Anei
    r = client.post("/api/login", json={"login": "ana", "password": "ghicit123"})
    assert r.status_code == 401

    bob = login("Bob", password="parola-bob1")
    assert client.get("/api/questions", headers=bob).json() == []
    assert len(client.get("/api/questions", headers=login("Ana", password="parola-ana1")).json()) == 1


def test_password_required_and_not_exposed():
    r = client.post("/api/students", json={"username": "ana", "name": "Ana", "password": "123"}, headers=login("Radu", "trainer"))
    assert r.status_code == 400
    login("Ana")
    assert "parola-test" not in str(app_module.db["users"])


def test_api_key_is_never_sent_to_browser():
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-secret"
    try:
        for path in ("/static/index.html", "/static/app.js"):
            assert "sk-ant" not in client.get(path).text
        ana = login("Ana")
        r = client.post("/api/proposals/refine", json={"title": "x"}, headers=ana)
        assert "sk-ant" not in r.text
    finally:
        del os.environ["ANTHROPIC_API_KEY"]


def test_refine_asks_at_most_three_questions_and_explains():
    ana = login("Ana")
    data = client.post("/api/proposals/refine", json={"title": "x"}, headers=ana).json()
    assert len(data["missing"]) <= 3
    assert "understood" in data


def test_config_lists_vibe_coding_topics():
    data = client.get("/api/config").json()
    assert data["ai"] is False
    assert {"prompting", "security", "claude-code", "deploy"} <= set(data["topics"])


def test_question_topic_falls_back_to_other():
    ana = login("Ana")
    q = client.post("/api/questions", json={"text": "Ceva?", "category": "nu-exista"}, headers=ana).json()
    assert q["category"] == "other"
    q = client.post("/api/questions", json={"text": "Ceva?", "category": "prompting"}, headers=ana).json()
    assert q["category"] == "prompting"


def test_ai_answer_only_for_own_question_and_needs_ai():
    ana, bob = login("Ana"), login("Bob")
    qid = client.post("/api/questions", json={"text": "Ce e un prompt?"}, headers=ana).json()["id"]
    assert client.post(f"/api/questions/{qid}/ai-answer", headers=bob).status_code == 403
    r = client.post(f"/api/questions/{qid}/ai-answer", headers=ana)
    assert r.status_code == 503  # AI oprit în teste: fără cheie, fără apel


def test_ai_answer_is_stored_once(monkeypatch):
    calls = []
    monkeypatch.setattr(app_module.ai, "available", lambda: True)
    monkeypatch.setattr(app_module.ai, "answer_question",
                        lambda text, topic, lang: calls.append(lang) or "Încearcă așa.")
    ana = login("Ana")
    qid = client.post("/api/questions", json={"text": "Ce e un prompt?"}, headers=ana).json()["id"]
    for _ in range(2):
        r = client.post(f"/api/questions/{qid}/ai-answer", headers={**ana, "X-Lang": "en"})
        assert r.json()["ai_answer"] == "Încearcă așa."
    assert calls == ["en"]


def test_errors_follow_selected_language():
    bad = {"login": "nimeni", "password": "orice-parola"}
    assert client.post("/api/login", json=bad, headers={"X-Lang": "en"}).json()["detail"] == "Wrong username or password."
    assert client.post("/api/login", json=bad).json()["detail"] == "Utilizator sau parolă greșită."


def test_local_refine_in_english():
    ana = login("Ana")
    r = client.post("/api/proposals/refine", json={"title": "quiz"}, headers={**ana, "X-Lang": "en"}).json()
    assert r["missing"][0]["question"].startswith("Briefly describe")


# ---------------------------------------------------------------- teme & proiecte

def submit(headers, files=None, **data):
    form = {"kind": "homework", "title": "Tema 1", **data}
    return client.post("/api/submissions", data=form, files=files or [], headers=headers)


def test_submission_private_to_author_and_trainer():
    ana, bob = login("Ana"), login("Bob")
    trainer = login("Radu", "trainer")
    r = submit(ana, files=[("files", ("tema.md", b"# Tema mea", "text/markdown"))],
               link="https://github.com/ana/cutia-clasei-ana", checklist=["no_keys", "nope"])
    assert r.status_code == 201, r.text
    sub = r.json()
    assert sub["checklist"] == ["no_keys"]
    assert "stored" not in sub["files"][0]
    fid = sub["files"][0]["id"]

    assert client.get("/api/submissions", headers=bob).json() == []
    assert len(client.get("/api/submissions", headers=trainer).json()) == 1
    # B nu poate descărca fișierul lui A
    assert client.get(f"/api/submissions/{sub['id']}/files/{fid}", headers=bob).status_code == 404
    d = client.get(f"/api/submissions/{sub['id']}/files/{fid}", headers=trainer)
    assert d.status_code == 200 and d.content == b"# Tema mea"
    assert d.headers["content-type"] == "application/octet-stream"
    assert "attachment" in d.headers["content-disposition"]


def test_submission_validation():
    ana = login("Ana")
    assert submit(ana, title="").status_code == 400
    assert submit(ana, link="javascript:alert(1)").status_code == 400
    assert submit(ana).status_code == 400  # nimic de predat
    bad = submit(ana, files=[("files", ("virus.exe", b"x", "application/octet-stream"))])
    assert bad.status_code == 400
    big = submit(ana, files=[("files", ("mare.pdf", b"x" * (10 * 1024 * 1024 + 1), "application/pdf"))])
    assert big.status_code == 400
    many = submit(ana, files=[("files", (f"f{i}.txt", b"x", "text/plain")) for i in range(6)])
    assert many.status_code == 400


def test_trainer_reviews_submission():
    ana, bob = login("Ana"), login("Bob")
    trainer = login("Radu", "trainer")
    sid = submit(ana, note="Am terminat!").json()["id"]
    body = {"status": "reviewed", "feedback": "Super, adaugă README."}
    assert client.post(f"/api/submissions/{sid}/review", json=body, headers=bob).status_code == 403
    r = client.post(f"/api/submissions/{sid}/review", json=body, headers=trainer)
    assert r.json()["status"] == "reviewed"
    assert client.get("/api/submissions", headers=ana).json()[0]["feedback"] == "Super, adaugă README."


# ---------------------------------------------------------------- sesiuni & preferințe

def test_session_survives_restart_and_logout_ends_it():
    ana = login("Ana")
    token = ana["Authorization"].split()[1]
    other = login("Ana")                                  # același student, alt dispozitiv
    assert client.get("/api/me", headers=ana).json()["name"] == "Ana"
    client.post("/api/logout", headers=ana)
    assert client.get("/api/me", headers=ana).status_code == 401
    assert token not in str(app_module.db["revoked"])      # se salvează doar hash-ul
    assert client.get("/api/me", headers=other).status_code == 200   # „Ieși” nu scoate celelalte dispozitive


def test_prefs_are_saved():
    ana = login("Ana")
    r = client.patch("/api/me", json={"lang": "fr", "hide_from_leaderboard": True}, headers=ana)
    assert r.json()["prefs"] == {"lang": "fr", "hide_from_leaderboard": True}
    assert client.patch("/api/me", json={"lang": "xx"}, headers=ana).json()["prefs"]["lang"] == "fr"


def test_errors_in_french():
    r = client.post("/api/login", json={"login": "nimeni", "password": "orice-parola"}, headers={"X-Lang": "fr"})
    assert r.json()["detail"] == "Identifiant ou mot de passe incorrect."


# ---------------------------------------------------------------- mesaje directe

def test_direct_messages_are_private():
    ana, bob = login("Ana"), login("Bob")
    trainer = login("Radu", "trainer")
    client.post("/api/dm", json={"text": "Bună! Am o întrebare despre temă."}, headers=ana)
    assert client.get("/api/dm", headers=bob).json()["messages"] == []
    assert client.get("/api/dm/ana", headers=bob).status_code == 403
    assert client.get("/api/dm/unread", headers=trainer).json()["unread"] == 1

    threads = client.get("/api/dm", headers=trainer).json()["threads"]
    ana_thread = next(t for t in threads if t["student_key"] == "ana")
    assert ana_thread["unread"] == 1
    assert len(client.get("/api/dm/ana", headers=trainer).json()["messages"]) == 1
    assert client.get("/api/dm/unread", headers=trainer).json()["unread"] == 0  # citit

    client.post("/api/dm/ana", json={"text": "Sigur, spune!"}, headers=trainer)
    assert client.get("/api/dm/unread", headers=ana).json()["unread"] == 1
    msgs = client.get("/api/dm", headers=ana).json()["messages"]
    assert [m["from_role"] for m in msgs] == ["student", "trainer"]
    assert client.get("/api/dm/unread", headers=ana).json()["unread"] == 0
    assert client.post("/api/dm/nimeni", json={"text": "x"}, headers=trainer).status_code == 404


# ---------------------------------------------------------------- puncte

def test_points_follow_the_rules(monkeypatch):
    monkeypatch.setattr(app_module.points, "QUESTS_PER_WEEK", 0)  # misiunile au testul lor
    ana, bob, cris = login("Ana"), login("Bob"), login("Cris")
    trainer = login("Radu", "trainer")
    a = client.post("/api/assignments", json={"title": "Tema 1", "due_at": "2999-01-01T00:00:00Z", "points": 25},
                    headers=trainer).json()
    sid = submit(ana, note="gata", assignment_id=str(a["id"])).json()["id"]
    submit(ana, note="din nou", assignment_id=str(a["id"]))           # a doua predare la aceeași temă nu mai punctează
    client.post(f"/api/submissions/{sid}/review", json={"status": "reviewed"}, headers=trainer)
    pid = client.post("/api/proposals", json={"title": "Quiz", "description": "Un quiz.", "audience": "Clasa",
                                              "approved": True}, headers=ana).json()["id"]
    assert client.post(f"/api/proposals/{pid}/vote", headers=ana).status_code == 400  # nu-ți votezi ideea
    client.post(f"/api/proposals/{pid}/vote", headers=bob)
    client.post(f"/api/proposals/{pid}/vote", headers=cris)
    client.post(f"/api/proposals/{pid}/choose", headers=trainer)
    for i in range(5):
        client.post("/api/questions", json={"text": f"Întrebarea {i}?"}, headers=ana)
    client.post("/api/points/bonus", json={"student_key": "ana", "points": 7, "reason": "Ajutor colegilor"},
                headers=trainer)

    me = client.get("/api/points/me", headers=ana).json()
    # 10 predare + 5 la timp + 25 revizuit + 5 idee + 4 voturi + 30 aleasă + 6 întrebări (max 3/zi) + 7 bonus
    assert me["total"] == 92
    assert me["level"]["key"] == "apprentice"
    assert {"first_homework", "first_idea", "chosen", "first_question"} <= set(me["badges"])


def test_bonus_rules_and_access():
    ana = login("Ana")
    trainer = login("Radu", "trainer")
    body = {"student_key": "ana", "points": 10, "reason": "x"}
    assert client.post("/api/points/bonus", json=body, headers=ana).status_code == 403
    assert client.post("/api/points/bonus", json={**body, "points": 0}, headers=trainer).status_code == 400
    assert client.post("/api/points/bonus", json={**body, "reason": " "}, headers=trainer).status_code == 400
    assert client.post("/api/points/bonus", json={**body, "student_key": "zz"}, headers=trainer).status_code == 404
    assert client.get("/api/points/ana", headers=ana).status_code == 403


def test_leaderboard_respects_hide():
    ana, bob = login("Ana"), login("Bob")
    trainer = login("Radu", "trainer")
    client.patch("/api/me", json={"hide_from_leaderboard": True}, headers=ana)
    names_bob = [r["name"] for r in client.get("/api/leaderboard", headers=bob).json()]
    assert "Ana" not in names_bob and "Bob" in names_bob
    assert any(r["me"] for r in client.get("/api/leaderboard", headers=ana).json())  # se vede pe sine
    assert "Ana" in [r["name"] for r in client.get("/api/leaderboard", headers=trainer).json()]
    assert "key" not in client.get("/api/leaderboard", headers=bob).json()[0]


# ---------------------------------------------------------------- teme & anunțuri

def test_assignments_and_announcements():
    ana = login("Ana")
    trainer = login("Radu", "trainer")
    assert client.post("/api/assignments", json={"title": "T"}, headers=ana).status_code == 403
    a = client.post("/api/assignments", json={"title": "Tema 2", "due_at": "2030-05-01T18:00"}, headers=trainer).json()
    assert a["due_at"] == "2030-05-01T18:00:00+00:00"
    assert client.get("/api/assignments", headers=ana).json()[0]["submitted"] is False
    submit(ana, note="x", assignment_id=str(a["id"]))
    assert client.get("/api/assignments", headers=ana).json()[0]["submitted"] is True
    assert submit(ana, note="x", assignment_id="9999").status_code == 404

    client.post("/api/announcements", json={"text": "Ora de joi începe la 18:30", "pinned": True}, headers=trainer)
    assert client.get("/api/announcements", headers=ana).json()[0]["pinned"] is True
    assert client.post("/api/announcements", json={"text": "x"}, headers=ana).status_code == 403


# ---------------------------------------------------------------- AI News

RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Startup launches new AI coding agent for beginners</title><link>https://example.com/agent</link>
<description>&lt;p&gt;A free &lt;b&gt;app&lt;/b&gt; that builds apps&lt;/p&gt;</description><pubDate>Mon, 05 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title>AI company faces lawsuit over stock valuation</title><link>https://example.com/lawsuit</link>
<description>Earnings news</description></item>
<item><title>Evil link</title><link>javascript:alert(1)</link></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Open-source model released with a new reasoning benchmark</title>
<link rel="alternate" href="https://example.org/model"/><updated>2026-10-04T08:00:00Z</updated>
<summary>Try the new model today</summary></entry>
<entry><title>Startup launches new AI coding agent for beginners</title><link href="https://dup.example/x"/></entry>
</feed>"""


def test_news_parsing_filtering_and_dedupe(monkeypatch):
    from src import news
    monkeypatch.setenv("CUTIA_NEWS_FEEDS", "A|https://a.example/rss,B|https://b.example/atom")
    fixtures = {"A": RSS, "B": ATOM}
    items, errors = news.collect(lambda su: (news.parse_feed(fixtures[su[0]], su[0]), None))
    titles = [it["title"] for it in items]
    assert "Startup launches new AI coding agent for beginners" in titles
    assert "Open-source model released with a new reasoning benchmark" in titles
    assert not any("lawsuit" in t for t in titles)              # filtrat
    assert len(titles) == 2                                       # duplicat scos, link javascript: ignorat
    agent = next(it for it in items if "agent" in it["title"])
    assert agent["summary"] == "A free app that builds apps"      # fără HTML
    assert agent["category"] == "launch"


def test_news_endpoint_without_ai(monkeypatch):
    from src import news
    monkeypatch.setattr(news, "_cache", {"at": 0.0, "items": [], "errors": [], "curated": {}})
    monkeypatch.setattr(news, "_fetch", lambda su: (news.parse_feed(RSS, "Test"), None))
    monkeypatch.setattr(news, "feeds", lambda: [("Test", "https://t.example/rss")])
    ana = login("Ana")
    data = client.get("/api/news", headers=ana).json()
    assert data["curated"] is False
    assert data["items"][0]["link"] == "https://example.com/agent"
    assert client.get("/api/news").status_code == 401


# ---------------------------------------------------------------- traduceri

def test_all_languages_are_complete():
    import shutil
    import subprocess
    from pathlib import Path
    if not shutil.which("node"):
        pytest.skip("node nu e instalat")
    script = Path(__file__).parent / "check_i18n.js"
    r = subprocess.run(["node", str(script), "en", "ro", "fr", "it", "es", "de"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert set(app_module.ai.LANGS) == {"ro", "en", "fr", "it", "es", "de"}
    assert all(len(v) == len(app_module.ai.LANGS) for v in app_module.MESSAGES.values())


def test_change_password():
    ana = login("Ana")
    body = {"current": "gresita!!", "new": "parola-noua-1"}
    assert client.post("/api/me/password", json=body, headers=ana).status_code == 403
    assert client.post("/api/me/password", json={**body, "current": "parola-test", "new": "scurt"}, headers=ana).status_code == 400
    r = client.post("/api/me/password", json={**body, "current": "parola-test"}, headers=ana)
    assert r.status_code == 200
    assert client.get("/api/me", headers=ana).status_code == 401           # alte dispozitive ies
    assert client.post("/api/login", json={"login": "ana", "password": "parola-noua-1"}).status_code == 200
    me = client.get("/api/me", headers=auth(r)).json()                       # dispozitivul curent rămâne logat
    assert me["login"] == "ana" and me["has_password"] is True


# ---------------------------------------------------------------- retragere & ciorne

def make_proposal(headers, title="Quiz"):
    body = {"title": title, "description": "Un quiz.", "audience": "Clasa", "approved": True}
    return client.post("/api/proposals", json=body, headers=headers).json()["id"]


def test_author_can_withdraw_and_restore_a_proposal(monkeypatch):
    monkeypatch.setattr(app_module.points, "QUESTS_PER_WEEK", 0)
    ana, bob = login("Ana"), login("Bob")
    trainer = login("Radu", "trainer")
    pid = make_proposal(ana)
    make_proposal(ana, "A doua idee")                      # se pot trimite mai multe
    client.post(f"/api/proposals/{pid}/vote", headers=bob)
    assert client.post(f"/api/proposals/{pid}/withdraw", json={"reason": "resolved"}, headers=bob).status_code == 403

    r = client.post(f"/api/proposals/{pid}/withdraw", json={"reason": "resolved", "note": "Am găsit o soluție"}, headers=ana)
    assert r.json()["status"] == "withdrawn" and r.json()["withdrawn_reason"] == "resolved"
    assert [p["title"] for p in client.get("/api/proposals", headers=bob).json()] == ["A doua idee"]
    assert len(client.get("/api/proposals", headers=ana).json()) == 2        # autorul o vede în continuare
    assert len(client.get("/api/proposals", headers=trainer).json()) == 2
    assert client.post(f"/api/proposals/{pid}/vote", headers=bob).status_code == 400
    assert client.post(f"/api/proposals/{pid}/choose", headers=trainer).status_code == 400
    # Idee retrasă = fără puncte pentru idee și voturi; rămâne doar a doua idee (+5)
    assert client.get("/api/points/me", headers=ana).json()["total"] == 5

    assert client.post(f"/api/proposals/{pid}/restore", headers=ana).json()["status"] == "active"
    assert len(client.get("/api/proposals", headers=bob).json()) == 2


def test_drafts_are_private_and_limited():
    ana, bob = login("Ana"), login("Bob")
    d = client.post("/api/drafts", json={"title": "Idee", "description": "ceva"}, headers=ana).json()
    assert client.get("/api/drafts", headers=bob).json() == []
    assert client.put(f"/api/drafts/{d['id']}", json={"title": "x"}, headers=bob).status_code == 404
    assert client.delete(f"/api/drafts/{d['id']}", headers=bob).status_code == 404
    r = client.put(f"/api/drafts/{d['id']}", json={"title": "Idee mai bună", "description": "ceva", "audience": "noi"}, headers=ana)
    assert r.json()["title"] == "Idee mai bună" and "owner" not in r.json()
    for _ in range(19):
        client.post("/api/drafts", json={"title": "x"}, headers=ana)
    assert client.post("/api/drafts", json={"title": "prea multe"}, headers=ana).status_code == 400
    assert client.delete(f"/api/drafts/{d['id']}", headers=ana).status_code == 200
    assert len(client.get("/api/drafts", headers=ana).json()) == 19



# ---------------------------------------------------------------- Byte: briefing-ul zilei

from datetime import datetime as _dt, timedelta as _td, timezone as _tz
from src import digest as digest_mod


def _fresh_feed(n=8):
    now = _dt.now(_tz.utc)
    items = "".join(
        f"<item><title>New AI coding agent launches tool number {i}</title><link>https://news.example/{i}</link>"
        f"<description>Developers can try the app {i}</description>"
        f"<pubDate>{(now - _td(hours=i)).strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate></item>" for i in range(n))
    old = "<item><title>Old model release from last month</title><link>https://news.example/old</link>" \
          f"<pubDate>{(now - _td(days=30)).strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate></item>"
    return f"<?xml version='1.0'?><rss version='2.0'><channel>{items}{old}</channel></rss>"


@pytest.fixture
def byte(monkeypatch):
    from src import news
    monkeypatch.setenv("CUTIA_NEWS_FEEDS", "Feed|https://feed.example/rss")
    monkeypatch.setattr(app_module, "run_digest_in_background", lambda: None)  # în teste rulăm noi, sincron
    app_module.db["digests"] = []
    feed = _fresh_feed()
    return lambda: app_module.make_digest(lambda su: (news.parse_feed(feed, su[0]), None))


def test_digest_keeps_last_24_hours_and_works_without_ai(byte):
    h = login("Ana")
    assert client.get("/api/digest", headers=h).json()["digest"] is None
    byte()
    data = client.get("/api/digest", headers=h).json()
    d = data["digest"]
    assert d["ai"] is False and d["window_hours"] == 24
    assert d["stats"] == {"sources": 1, "scanned": 9, "fresh": 8, "picked": 6}
    assert len(d["stories"]) == 6 and all("old" not in s["link"] for s in d["stories"])
    assert d["tool"]["link"].startswith("https://news.example/")
    assert data["history"] == [d["date"]] and "pool" not in d and "by_lang" not in d
    assert client.get("/api/digest").status_code == 401  # doar pentru cei logați


def test_digest_written_by_ai_once_per_language(byte, monkeypatch):
    calls = []

    def fake_write(d, lang, ai_module):
        calls.append(lang)
        return digest_mod.validate(d, {
            "line": "Bună dimineața!", "title": "Ziua agenților", "tldr": "Agenți noi.", "pulse": 9,
            "stories": [{"id": "n1", "headline": "H1", "why": "W", "for_you": "F"},
                        {"id": "inventat", "headline": "Fals", "why": "", "for_you": ""}],
            "tool": {"id": "n2", "name": "Unealta", "what": "Face X", "try_prompt": "Explică-mi X"},
            "challenge": {"title": "15 minute", "steps": ["a", "b", "c", "d"]},
            "word": {"term": "agent", "explain": "Un AI care face pași singur."}})
    monkeypatch.setattr(app_module.ai, "available", lambda: True)
    monkeypatch.setattr(digest_mod, "write", fake_write)
    byte()
    assert calls == ["ro", "en"]  # limbile implicite, scrise dimineața
    h = login("Ana")
    d = client.get("/api/digest", headers=h).json()["digest"]
    assert d["ai"] and d["title"] == "Ziua agenților" and d["pulse"] == 5
    assert [s["id"] for s in d["stories"]] == ["n1"]                 # id-ul inventat dispare
    assert d["stories"][0]["link"] == "https://news.example/1"       # linkul vine din flux, nu de la AI
    assert d["tool"]["link"] == "https://news.example/2" and len(d["challenge"]["steps"]) == 3
    client.get("/api/digest", headers={**h, "X-Lang": "fr"})
    client.get("/api/digest", headers={**h, "X-Lang": "fr"})
    assert calls == ["ro", "en", "fr"]  # franceza: o singură dată, apoi din memorie


def test_digest_ai_failure_falls_back_and_waits_before_retry(byte, monkeypatch):
    calls = []
    monkeypatch.setattr(app_module.ai, "available", lambda: True)
    monkeypatch.setattr(digest_mod, "write", lambda d, lang, ai_module: calls.append(lang))
    byte()
    h = login("Ana")
    d = client.get("/api/digest", headers=h).json()["digest"]
    assert d["ai"] is False and len(d["stories"]) == 6
    client.get("/api/digest", headers=h)
    assert calls == ["ro", "en"]  # nu reîncercăm la fiecare vizită


def test_only_trainer_can_rerun_digest(byte):
    assert client.post("/api/digest/run", headers=login("Ana")).status_code == 403
    assert client.post("/api/digest/run", headers=login("Radu", "trainer")).status_code == 200


def test_digest_is_due_once_a_day():
    today = digest_mod.today()
    assert digest_mod.due([{"date": today}]) is False
    assert digest_mod.next_run() > _dt.now(_tz.utc).isoformat()


def test_weak_trainer_codes_are_ignored(monkeypatch):
    # Codul din README / .env.example îl știe oricine: nu face pe nimeni trainer
    monkeypatch.setattr(app_module, "TRAINER_CODE", "")
    for code in ("schimba-ma", ""):
        assert client.post("/api/setup", json={**TRAINER, "trainer_code": code}).status_code == 403


def test_health_and_atomic_save(tmp_path, monkeypatch):
    assert client.get("/api/health").json() == {"ok": True, "storage": "file", "serverless": False}
    monkeypatch.setenv("CUTIA_PERSIST", "1")
    monkeypatch.setattr(app_module, "DATA_FILE", tmp_path / "cutia.json")
    app_module.save_db()
    assert [f.name for f in tmp_path.iterdir()] == ["cutia.json"]  # fără fișiere .tmp rămase


# ---------------------------------------------------------------- Atelier: Verifică repo-ul (GitHub fals)

from src import repocheck

FAKE_KEY = "sk-ant-api03-" + "x" * 40


class FakeGitHub:
    def __init__(self, files, history=None):
        self.files, self.history, self.calls = files, history or [], []

    def handler(self, request):
        self.calls.append(str(request.url))
        host, path = request.url.host, request.url.path
        if host == "raw.githubusercontent.com":
            name = path.split("/", 4)[4]
            return httpx.Response(200, text=self.files[name]) if name in self.files else httpx.Response(404)
        if path == "/repos/ana/app":
            return httpx.Response(200, json={"default_branch": "main"})
        if path == "/repos/ana/app/commits/main":
            return httpx.Response(200, json={"sha": "abc1234567"})
        if path == "/repos/ana/app/git/trees/abc1234567":
            return httpx.Response(200, json={"tree": [{"path": p, "type": "blob", "size": len(c)} for p, c in self.files.items()]})
        if path == "/repos/ana/app/commits":
            return httpx.Response(200, json=[{"sha": f"c{i}000000"} for i in range(len(self.history))])
        if path.startswith("/repos/ana/app/commits/c"):
            i = int(path.rsplit("/", 1)[1][1])
            return httpx.Response(200, json={"files": [{"filename": "app.py", "patch": self.history[i]}]})
        return httpx.Response(404)


GOOD_README = "# App\n## Ce face\nAjută clasa.\n## Cum se pornește\npip install -r requirements.txt\n## Funcții în plus\nTeme.\nLive: https://app.onrender.com\n"


@pytest.fixture
def github(monkeypatch):
    def make(files, history=None):
        fake = FakeGitHub(files, history)
        monkeypatch.setattr(repocheck, "_transport", httpx.MockTransport(fake.handler))
        monkeypatch.setattr(repocheck, "_cache", {})
        return fake
    return make


def test_repo_check_clean_repo(github):
    github({"README.md": GOOD_README, ".gitignore": "data/\n.env\n", "app.py": "import os\nKEY = os.environ['X']\n", ".env.example": "ANTHROPIC_API_KEY=\n"},
           ["+import os"])
    r = client.post("/api/repo-check", headers=login("Ana"), json={"url": "https://github.com/ana/app"})
    assert r.status_code == 200, r.text
    status = {c["key"]: c["status"] for c in r.json()["checks"]}
    assert status == {"readme": "ok", "readme_what": "ok", "readme_run": "ok", "readme_extras": "ok", "live_link": "ok",
                      "gitignore_env": "ok", "no_env_file": "ok", "no_keys_now": "ok", "no_keys_history": "ok", "trainer_access": "manual"}
    assert r.json()["passed"] == r.json()["total"] == 9


def test_repo_check_finds_keys_env_and_history(github):
    github({"README.md": "# App", "app.py": f"KEY = '{FAKE_KEY}'\n", ".env": f"ANTHROPIC_API_KEY={FAKE_KEY}\n"},
           [f"+KEY = '{FAKE_KEY}'", "-old line"])
    r = client.post("/api/repo-check", headers=login("Ana"), json={"url": "https://github.com/ana/app.git"}).json()
    checks = {c["key"]: c for c in r["checks"]}
    assert checks["gitignore_env"]["status"] == "fail"
    assert checks["no_env_file"]["detail"] == [".env"]
    assert {d["file"] for d in checks["no_keys_now"]["detail"]} == {"app.py", ".env"}
    assert checks["no_keys_history"]["detail"][0]["commit"] == "c000000"
    # Cheia nu apare niciodată întreagă în răspuns
    assert FAKE_KEY not in _json.dumps(r) and checks["no_keys_now"]["detail"][0]["masked"].startswith("sk-ant")


def test_repo_check_rejects_other_hosts_and_needs_login(github):
    fake = github({})
    h = login("Ana")
    for url in ["https://evil.example/ana/app", "http://169.254.169.254/latest", "https://github.com/ana", "javascript:alert(1)"]:
        assert client.post("/api/repo-check", headers=h, json={"url": url + "?" * 0}).status_code in (400, 422), url
    assert fake.calls == []  # nu am întrebat nimic în afara GitHub-ului
    assert client.post("/api/repo-check", json={"url": "https://github.com/ana/app"}).status_code == 401


def test_repo_check_missing_repo_and_cooldown(github):
    github({})
    h = login("Ana")
    r = client.post("/api/repo-check", headers=h, json={"url": "https://github.com/nimeni/nimic"})
    assert r.status_code == 404
    assert client.post("/api/repo-check", headers=h, json={"url": "https://github.com/nimeni/nimic"}).status_code == 429


def test_find_keys_detects_supabase_service_role():
    payload = base64.urlsafe_b64encode(_json.dumps({"role": "service_role"}).encode()).decode().rstrip("=")
    token = f"eyJhbGciOiJIUzI1NiJ9.{payload}.signaturesignature"
    assert repocheck.find_keys(f"const k = '{token}'")[0][0] == "Supabase service_role"
    anon = base64.urlsafe_b64encode(_json.dumps({"role": "anon"}).encode()).decode().rstrip("=")
    assert repocheck.find_keys(f"eyJhbGciOiJIUzI1NiJ9.{anon}.signaturesignature") == []


# ---------------------------------------------------------------- Error Doctor + Prompt Lab + Hall

PNG_1PX = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                        "1f15c4890000000d49444154789c6360000002000100ffff03000006000557bfabd40000000049454e44ae426082")


def test_doctor_local_hides_keys_and_is_private():
    ha, hb = login("Ana"), login("Vlad")
    r = client.post("/api/doctor", headers=ha, data={"text": f"Error: invalid x-api-key {FAKE_KEY}"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["ai"] is False and d["local"] == "api_key" and d["had_key"] is True
    assert FAKE_KEY not in _json.dumps(app_module.db["doctor"]) and "[KEY HIDDEN]" in d["excerpt"]
    assert len(client.get("/api/doctor", headers=ha).json()) == 1
    assert client.get("/api/doctor", headers=hb).json() == []                      # Vlad nu vede istoricul Anei
    assert client.delete(f"/api/doctor/{d['id']}", headers=hb).status_code == 404
    assert client.delete(f"/api/doctor/{d['id']}", headers=ha).status_code == 200


def test_doctor_validates_input_and_uses_ai(monkeypatch):
    h = login("Ana")
    assert client.post("/api/doctor", headers=h, data={"text": ""}).status_code == 400
    fake_png = ("x.png", b"<svg onload=alert(1)>", "image/png")
    assert client.post("/api/doctor", headers=h, data={"text": "x"}, files={"image": fake_png}).status_code == 400
    seen = {}

    def fake_diagnose(text, image, lang):
        seen.update(text=text, image=image, lang=lang)
        return {"title": "Lipsește modulul", "explain": "E", "cause": "C", "steps": ["pip install x"], "prompt": "P", "severity": "easy"}
    monkeypatch.setattr(app_module.ai, "available", lambda: True)
    monkeypatch.setattr(app_module.tools, "diagnose", fake_diagnose)
    r = client.post("/api/doctor", headers={**h, "X-Lang": "en"}, data={"text": "No module named x"},
                    files={"image": ("s.png", PNG_1PX, "image/png")})
    assert r.status_code == 201 and r.json()["ai"] and r.json()["result"]["title"] == "Lipsește modulul"
    assert seen["image"][0] == "image/png" and seen["lang"] == "en"
    assert client.post("/api/doctor", headers=h, data={"text": "again"}).status_code == 429  # pauză între cereri


def test_local_error_patterns():
    from src import tools
    cases = {"ModuleNotFoundError: No module named 'fastapi'": "module_missing", "Error: listen EADDRINUSE :::3000": "port_busy",
             "! [rejected] main -> main (fetch first)": "git_rejected", "SyntaxError: Unexpected token '}'": "syntax",
             "TypeError: Cannot read properties of undefined": "undefined", "ceva ciudat": "generic"}
    for text, key in cases.items():
        assert tools.local_match(text) == key, text


def test_prompt_lab_local_scores():
    h = login("Ana")
    weak = client.post("/api/prompt-lab", headers=h, json={"prompt": "fa o aplicatie"}).json()
    strong = client.post("/api/prompt-lab", headers=login("Vlad"), json={"prompt":
        "Am o aplicație pentru clasa mea de vibe coding, folosesc FastAPI. Vreau să adaugi un buton de export. "
        "Fără librării noi, doar pas cu pas. Exemplu: „Export CSV” descarcă întrebările."}).json()
    assert weak["ai"] is False and sum(weak["scores"].values()) < sum(strong["scores"].values())
    assert all(0 <= v <= 5 for v in strong["scores"].values())


def test_hall_of_prompts_likes_and_ownership():
    ha, hb, ht = login("Ana"), login("Vlad"), login("Radu", "trainer")
    h = client.post("/api/hall", headers=ha, json={"title": "Debug pas cu pas", "prompt": f"Explică eroarea pas cu pas {FAKE_KEY}"}).json()
    assert FAKE_KEY not in h["prompt"]
    assert client.post(f"/api/hall/{h['id']}/like", headers=ha).status_code == 400        # nu-ți dai like singur
    assert client.post(f"/api/hall/{h['id']}/like", headers=hb).json()["likes"] == 1
    listed = client.get("/api/hall", headers=hb).json()[0]
    assert listed["author"] == "Ana" and listed["liked"] and "author_key" not in listed and "@" not in _json.dumps(listed)
    assert client.delete(f"/api/hall/{h['id']}", headers=hb).status_code == 403
    assert client.delete(f"/api/hall/{h['id']}", headers=ht).status_code == 200            # trainerul poate modera


def test_each_key_is_reported_once():
    assert [k for k, _ in repocheck.find_keys(FAKE_KEY)] == ["Anthropic"]
    assert [k for k, _ in repocheck.find_keys("sk-proj-" + "a" * 40)] == ["OpenAI"]


# ---------------------------------------------------------------- Ora live

def test_live_class_flow_and_privacy():
    ha, hb, ht = login("Ana"), login("Vlad"), login("Radu", "trainer")
    assert client.get("/api/live", headers=ha).json() == {"active": False, "last_ended_at": None}
    assert client.post("/api/live/stuck", headers=ha).status_code == 409          # fără oră pornită
    assert client.post("/api/live/start", headers=ha, json={}).status_code == 403  # doar trainerul pornește ora
    assert client.post("/api/live/start", headers=ht, json={"title": "Supabase"}).json()["active"]

    # „M-am blocat”: anonim, doar un număr
    v = client.post("/api/live/stuck", headers=ha).json()
    assert v["stuck"] == 1 and v["me_stuck"] and "Ana" not in _json.dumps(v)
    assert client.get("/api/live", headers=ht).json()["stuck"] == 1

    # Vot: rezultatele apar după ce votezi
    client.post("/api/live/polls", headers=ht, json={"question": "Ați terminat?", "options": ["Da", "Aproape", ""]})
    poll = client.get("/api/live", headers=ha).json()["polls"][0]
    assert poll["options"] == ["Da", "Aproape"] and poll["results"] is None
    assert client.post(f"/api/live/polls/{poll['id']}/vote", headers=ha, json={"option": 1}).json()["polls"][0]["results"] == [0, 1]
    assert client.post("/api/live/polls", headers=ht, json={"question": "Gata?", "options": ["doar una"]}).status_code == 400

    # Coada de întrebări: anonimatul ascunde numele de toți
    q = client.post("/api/live/questions", headers=ha, json={"text": "Cum pun cheia în Render?", "anonymous": True}).json()["queue"][0]
    assert q["author"] is None
    assert client.post(f"/api/live/questions/{q['id']}/upvote", headers=ha).status_code == 400
    assert client.post(f"/api/live/questions/{q['id']}/upvote", headers=hb).json()["queue"][0]["upvotes"] == 1
    assert "Ana" not in _json.dumps(client.get("/api/live", headers=ht).json()["queue"])

    # Biletul de ieșire: doar trainerul vede toate răspunsurile
    client.post("/api/live/ticket", headers=ht, json={"question": "Ce ai învățat azi?"})
    client.post("/api/live/ticket/answer", headers=ha, json={"text": "Cum ascund cheile"})
    assert client.get("/api/live", headers=hb).json()["ticket"] == {"question": "Ce ai învățat azi?", "my_answer": None, "count": 1, "answers": None}
    assert client.get("/api/live", headers=ha).json()["ticket"]["my_answer"] == "Cum ascund cheile"
    assert client.get("/api/live", headers=ht).json()["ticket"]["answers"][0]["name"] == "Ana"

    end = client.post("/api/live/end", headers=ht).json()
    assert end == {"active": False, "last_ended_at": app_module.db["live_history"][-1]["ended_at"]}


# ---------------------------------------------------------------- Demo Day + Kickstart kit

def test_showcase_flow_points_and_safety():
    ha, hb, ht = login("Ana"), login("Vlad"), login("Radu", "trainer")
    assert client.post("/api/showcase", headers=ha, data={"title": "Fără linkuri"}).status_code == 400
    assert client.post("/api/showcase", headers=ha, data={"title": "X", "live_url": "javascript:alert(1)"}).status_code == 400
    fake = ("x.png", b"<svg onload=alert(1)>", "image/png")
    assert client.post("/api/showcase", headers=ha, data={"title": "X", "live_url": "https://a.app"}, files={"image": fake}).status_code == 400
    assert client.post("/api/showcase", headers=ht, data={"title": "X", "live_url": "https://a.app"}).status_code == 403
    r = client.post("/api/showcase", headers=ha, data={"title": "Habit tracker", "description": "Făcut cu Claude", "live_url": "https://habit.app"},
                    files={"image": ("s.png", PNG_1PX, "image/png")})
    assert r.status_code == 201 and r.json()["has_image"]
    sid = r.json()["id"]
    img = client.get(f"/api/showcase/{sid}/image", headers=hb)
    assert img.content == PNG_1PX and img.headers["content-type"] == "image/png" and img.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/api/showcase/{sid}/image").status_code == 401

    assert client.post(f"/api/showcase/{sid}/react", headers=ha, json={"emoji": "🔥"}).status_code == 400   # nu la propriul proiect
    assert client.post(f"/api/showcase/{sid}/react", headers=hb, json={"emoji": "🔥"}).json()["reactions"]["🔥"] == 1
    assert client.post(f"/api/showcase/{sid}/spotlight", headers=hb).status_code == 403
    assert client.post(f"/api/showcase/{sid}/spotlight", headers=ht).json()["spotlight"] is True
    pts = client.get("/api/points/me", headers=ha).json()
    assert {"showcase", "spotlight"} <= {e["kind"] for e in pts["events"]} and "demo_day" in pts["badges"]
    listed = client.get("/api/showcase", headers=hb).json()[0]
    assert "author_key" not in listed and "@" not in _json.dumps(listed)
    assert client.delete(f"/api/showcase/{sid}", headers=hb).status_code == 403
    assert client.delete(f"/api/showcase/{sid}", headers=ha).status_code == 200


def test_kickstart_only_for_chosen_ideas_and_cached(monkeypatch):
    ha, ht = login("Ana"), login("Radu", "trainer")
    p = client.post("/api/proposals", headers=ha, json={"title": "Teme", "description": "Notez temele", "audience": "Colegii", "approved": True}).json()
    assert client.get(f"/api/proposals/{p['id']}/kickstart", headers=ha).status_code == 400
    client.post(f"/api/proposals/{p['id']}/choose", headers=ht)
    assert client.get(f"/api/proposals/{p['id']}/kickstart", headers=ha).json() == {"ai": False}   # fără AI: șablon în interfață
    calls = []
    monkeypatch.setattr(app_module.ai, "available", lambda: True)
    monkeypatch.setattr(app_module.tools, "kickstart", lambda prop, lang: calls.append(lang) or {
        "ai": True, "first_prompt": "P", "first_hour": ["a"], "later": ["b"], "stack": "HTML", "risk": "r"})
    for _ in range(3):
        assert client.get(f"/api/proposals/{p['id']}/kickstart", headers=login("Vlad")).json()["first_prompt"] == "P"
    assert calls == ["ro"]


# ---------------------------------------------------------------- Serii, misiuni, recap, FAQ

def test_weekly_quests_and_streak(monkeypatch):
    from src import points as P
    monkeypatch.setattr(P, "quests_for", lambda week: [("ask", "question", 2), ("lab", "prompt_lab", 3), ("byte", "challenge", 2), ("idea", "idea", 1)])
    h = login("Ana")
    q = client.get("/api/quests", headers=h).json()
    assert q["streak"] == {"current": 0, "best": 0, "today": False} and all(not x["done"] for x in q["quests"])
    for text in ["Cum fac deploy pe Render?", "Ce e un mediu virtual?"]:
        client.post("/api/questions", headers=h, json={"text": text, "category": "deploy"})
    q = client.get("/api/quests", headers=h).json()
    ask = next(x for x in q["quests"] if x["key"] == "ask")
    assert ask["done"] and ask["progress"] == 2 and q["streak"]["current"] == 1 and q["streak"]["today"]
    assert {"kind": "quest", "points": 5} .items() <= next(e for e in client.get("/api/points/me", headers=h).json()["events"] if e["kind"] == "quest").items()
    # Byte: doar azi sau o zi cu briefing; nu în viitor
    today = P.today().isoformat()
    assert client.post("/api/challenge", headers=h, json={"date": "2099-01-01"}).status_code == 400
    assert client.post("/api/challenge", headers=h, json={"date": "2020-01-01"}).status_code == 400
    assert client.post("/api/challenge", headers=h, json={"date": today}).status_code == 200
    assert client.get("/api/quests", headers=login("Radu", "trainer")).status_code == 403


def test_streak_counts_consecutive_days():
    from src import points as P
    from datetime import timedelta as td
    d = P.today()
    acts = [("question", (d - td(days=i)).isoformat()) for i in (1, 2, 3)] + [("question", (d - td(days=9)).isoformat())]
    assert P.streaks(acts) == {"current": 3, "best": 3, "today": False}


def test_recap_is_trainer_only_and_sends_no_names(monkeypatch):
    ha, hb, ht = login("Ana"), login("Vlad"), login("Radu", "trainer")
    client.post("/api/questions", headers=ha, json={"text": "Cum ascund cheia API?", "category": "security"})
    qid = client.get("/api/questions", headers=ht).json()[0]["id"]
    assert client.post(f"/api/questions/{qid}/answer", headers=ht, json={"text": "O pui în .env, iar .env în .gitignore."}).status_code == 200
    assert client.get("/api/recap", headers=ha).status_code == 403
    r = client.get("/api/recap", headers=ht).json()
    assert r["stats"]["questions_new"] == 1 and r["stats"]["students"] == 2 and r["inactive"] == ["Vlad"]
    # Fără acordul studentului, întrebarea nu devine propunere de FAQ
    assert r["faq_suggestions"] == []
    client.post(f"/api/questions/{qid}/faq-consent", headers=ha, json={"faq_ok": True})
    r = client.get("/api/recap", headers=ht).json()
    assert r["faq_suggestions"] == [{"q": "Cum ascund cheia API?", "a": "O pui în .env, iar .env în .gitignore.", "question_id": qid}]
    sent = {}
    monkeypatch.setattr(app_module.ai, "available", lambda: True)
    monkeypatch.setattr(app_module.tools, "recap", lambda activity, lang: sent.update(activity=activity) or
                        {"summary": "S", "focus": ["F"], "faq": [{"q": "Q", "a": "A"}]})
    r = client.get("/api/recap?refresh=true", headers=ht).json()
    # Propunerile de FAQ vin doar din întrebările cu acord, nu din textul generat de AI
    assert r["ai"]["summary"] == "S" and r["faq_suggestions"][0]["question_id"] == qid
    assert "Ana" not in _json.dumps(sent) and "Vlad" not in _json.dumps(sent) and "@" not in _json.dumps(sent)


def test_faq_public_read_trainer_write():
    ha, ht = login("Ana"), login("Radu", "trainer")
    assert client.post("/api/faq", headers=ha, json={"q": "Întrebare?", "a": "Răspuns"}).status_code == 403
    f = client.post("/api/faq", headers=ht, json={"q": "Unde pun cheia API?", "a": "În .env, pe server."}).json()
    assert client.get("/api/faq", headers=ha).json()[0]["q"] == "Unde pun cheia API?"
    assert client.put(f"/api/faq/{f['id']}", headers=ha, json={"q": "x?", "a": "y"}).status_code == 403
    assert client.put(f"/api/faq/{f['id']}", headers=ht, json={"q": "Unde stă cheia API?", "a": "În .env."}).json()["q"] == "Unde stă cheia API?"
    assert client.delete(f"/api/faq/{f['id']}", headers=ht).status_code == 200


# ---------------------------------------------------------------- Notificări push (PWA)

from src import webpush
from cryptography.hazmat.primitives import hashes as _hashes, serialization as _ser
from cryptography.hazmat.primitives.asymmetric import ec as _ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AESGCM


class FakeBrowser:
    """Un browser abonat: are cheile lui și poate decripta ce primește (RFC 8291)."""

    def __init__(self, endpoint):
        self.key = _ec.generate_private_key(_ec.SECP256R1())
        self.public = self.key.public_key().public_bytes(_ser.Encoding.X962, _ser.PublicFormat.UncompressedPoint)
        self.auth = os.urandom(16)
        self.sub = {"endpoint": endpoint, "keys": {"p256dh": webpush.b64u(self.public), "auth": webpush.b64u(self.auth)}}

    def decrypt(self, body):
        salt, idlen = body[:16], body[20]
        as_public = body[21:21 + idlen]
        shared = self.key.exchange(_ec.ECDH(), _ec.EllipticCurvePublicKey.from_encoded_point(_ec.SECP256R1(), as_public))
        ikm = webpush._hkdf(self.auth, shared, b"WebPush: info\x00" + self.public + as_public, 32)
        cek = webpush._hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
        nonce = webpush._hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
        plain = _AESGCM(cek).decrypt(nonce, body[21 + idlen:], None)
        assert plain.endswith(b"\x02")
        return _json.loads(plain[:-1])


@pytest.fixture
def push(monkeypatch):
    pub, priv = webpush.generate_keys()
    monkeypatch.setenv("VAPID_PUBLIC_KEY", pub)
    monkeypatch.setenv("VAPID_PRIVATE_KEY", priv)
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:radu@test.ro")
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(410 if "gone" in str(request.url) else 201)
    monkeypatch.setattr(webpush, "_transport", httpx.MockTransport(handler))

    class Now:  # trimitem pe loc, nu în fundal, ca testul să vadă rezultatul
        def submit(self, fn, *args):
            fn(*args)
    monkeypatch.setattr(app_module, "_push_pool", Now())
    return sent


def test_push_message_is_encrypted_and_signed(push):
    browser = FakeBrowser("https://push.example/abc")
    webpush.send(browser.sub, {"title": "Cutia Clasei", "body": "Salut"})
    req = push[0]
    assert req.headers["content-encoding"] == "aes128gcm" and b"Salut" not in req.content
    assert browser.decrypt(req.content) == {"title": "Cutia Clasei", "body": "Salut"}
    # Semnătura VAPID se verifică cu cheia publică a serverului
    jwt = req.headers["authorization"].split("t=")[1].split(",")[0]
    head, claims, sig = jwt.split(".")
    assert _json.loads(webpush.unb64u(claims))["aud"] == "https://push.example"
    raw = webpush.unb64u(sig)
    server_key = _ec.EllipticCurvePublicKey.from_encoded_point(_ec.SECP256R1(), webpush.unb64u(os.environ["VAPID_PUBLIC_KEY"]))
    server_key.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                      f"{head}.{claims}".encode(), _ec.ECDSA(_hashes.SHA256()))


def test_push_reaches_the_right_person_in_their_language(push):
    ha, hb, ht = login("Ana"), login("Vlad"), login("Radu", "trainer")
    assert client.get("/api/config").json()["push_key"] == os.environ["VAPID_PUBLIC_KEY"]
    ana, vlad = FakeBrowser("https://push.example/ana"), FakeBrowser("https://push.example/vlad")
    assert client.post("/api/push/subscribe", headers=ha, json=ana.sub).json()["devices"] == 1
    client.post("/api/push/subscribe", headers=hb, json=vlad.sub)
    assert client.post("/api/push/subscribe", headers=ha, json={**ana.sub, "endpoint": "http://insecure.example/x"}).status_code == 400
    client.patch("/api/me", headers=ha, json={"lang": "en"})
    client.post("/api/questions", headers=ha, json={"text": "Cum fac deploy?", "category": "deploy"})
    qid = client.get("/api/questions", headers=ht).json()[0]["id"]
    client.post(f"/api/questions/{qid}/answer", headers=ht, json={"text": "Cu Render."})
    assert [str(r.url) for r in push] == ["https://push.example/ana"]                   # doar Ana, nu și Vlad
    msg = ana.decrypt(push[0].content)
    assert msg["body"] == "The trainer answered one of your questions." and msg["url"].endswith("#questions")
    assert "Render" not in _json.dumps(msg)                                                # fără conținut privat


def test_expired_subscription_is_removed(push):
    ha, ht = login("Ana"), login("Radu", "trainer")
    client.post("/api/push/subscribe", headers=ha, json=FakeBrowser("https://push.example/gone").sub)
    client.post("/api/live/start", headers=ht, json={})
    assert app_module.db["push"]["ana"] == []


# ---------------------------------------------------------------- Date și fișiere în Supabase (Supabase fals)

from src import store


class FakeSupabaseDB:
    """Imită funcțiile cutia_sync / cutia_commit (Postgres prin PostgREST) și Storage (bucket-ul cutia-files)."""

    def __init__(self, rows=None, down=False):
        self.rows = {k: {"version": 1, "data": v} for k, v in (rows or {}).items()}
        self.files, self.writes, self.down, self.headers, self.syncs = {}, [], down, [], 0

    def other_server_writes(self, name, data):
        """Altă copie a serverului (de ex. altă funcție Vercel) scrie între timp."""
        row = self.rows.setdefault(name, {"version": 0, "data": None})
        row.update(version=row["version"] + 1, data=data)

    def handler(self, request):
        self.headers.append(dict(request.headers))
        if self.down:
            raise httpx.ConnectError("down")
        path = request.url.path
        if path == "/rest/v1/rpc/cutia_sync":
            self.syncs += 1
            known = _json.loads(request.content)["known"]
            return httpx.Response(200, json=[
                {"name": k, "version": r["version"], "changed": known.get(k) != r["version"],
                 "data": r["data"] if known.get(k) != r["version"] else None} for k, r in self.rows.items()])
        if path == "/rest/v1/rpc/cutia_commit":
            changes = _json.loads(request.content)["changes"]
            conflict = [c["name"] for c in changes if self.rows.get(c["name"], {}).get("version", 0) != c["version"]]
            if conflict:
                return httpx.Response(200, json={"ok": False, "conflict": conflict})
            self.writes.append(sorted(c["name"] for c in changes))
            for c in changes:
                self.other_server_writes(c["name"], c["data"])
            return httpx.Response(200, json={"ok": True, "versions": {c["name"]: self.rows[c["name"]]["version"] for c in changes}})
        if path.startswith("/storage/v1/object/cutia-files/"):
            name = path.rsplit("/", 1)[1]
            if request.method == "POST":
                self.files[name] = request.content
                return httpx.Response(200, json={"Key": name})
            if request.method == "GET":
                return httpx.Response(200, content=self.files[name]) if name in self.files else httpx.Response(400, json={"error": "not_found"})
            if request.method == "DELETE":
                self.files.pop(name, None)
                return httpx.Response(200, json=[])
        return httpx.Response(404)


@pytest.fixture
def supa_db(monkeypatch, tmp_path):
    def make(rows=None, down=False, local=None):
        fake = FakeSupabaseDB(rows, down)
        monkeypatch.setenv("SUPABASE_URL", "https://proiect.supabase.co")
        monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_testkey_123456789")
        monkeypatch.setenv("CUTIA_PERSIST", "1")
        monkeypatch.setattr(store, "_transport", httpx.MockTransport(fake.handler))
        monkeypatch.setattr(app_module.time, "sleep", lambda s: None)
        data_file = tmp_path / "cutia.json"
        if local is not None:
            data_file.write_text(_json.dumps(local))
        monkeypatch.setattr(app_module, "DATA_FILE", data_file)
        return fake
    return make


def test_supabase_storage_loads_and_writes_only_changes(supa_db):
    fake = supa_db(rows={"users": {}, "questions": []})
    app_module.load_db()
    assert fake.writes == []
    h = login("Ana")
    fake.writes.clear()
    client.post("/api/questions", headers=h, json={"text": "Unde stau datele?", "category": "data"})
    assert fake.writes == [["next_id", "questions"]]                 # doar ce s-a schimbat, imediat
    assert fake.rows["questions"]["data"][0]["text"] == "Unde stau datele?"
    client.get("/api/questions", headers=h)
    assert len(fake.writes) == 1                                       # o citire nu scrie nimic
    # Cheia secretă merge doar ca apikey (cheile noi sb_secret_ nu sunt JWT) și nu ajunge în browser
    assert fake.headers[-1]["apikey"] == "sb_secret_testkey_123456789" and "authorization" not in fake.headers[-1]
    assert "sb_secret" not in client.get("/api/config").text
    assert client.get("/api/health").json()["storage"] == "supabase"


def test_supabase_sees_writes_from_other_servers(supa_db):
    """Pe Vercel rulează mai multe copii: fiecare cerere vede ce au scris celelalte."""
    fake = supa_db(rows={"users": {}, "questions": []})
    app_module.load_db()
    ht = login("Radu", "trainer")
    fake.other_server_writes("announcements", [{"id": 99, "text": "Scris de alt server", "by": "Radu", "pinned": False, "created_at": "2026-10-14"}])
    assert client.get("/api/announcements", headers=ht).json()[0]["text"] == "Scris de alt server"


def test_supabase_conflict_replays_the_request(supa_db):
    """Două servere scriu în același timp: al doilea reia cererea pe datele noi, nimic nu se pierde."""
    fake = supa_db(rows={"users": {}, "questions": []})
    app_module.load_db()
    ana = login("Ana")
    calls = {"n": 0}
    real_commit = store.commit

    def racing_commit(changes):
        calls["n"] += 1
        if calls["n"] == 1:   # chiar înainte să scriem noi, alt server adaugă o întrebare
            q = {"id": 500, "text": "De pe alt server", "category": "other", "anonymous": False, "faq_ok": False,
                 "author": "Ana", "author_key": "ana", "created_at": "2026-10-14T10:00:00+00:00",
                 "answer": None, "answered_at": None, "ai_answer": None, "ai_answered_at": None}
            fake.other_server_writes("questions", fake.rows["questions"]["data"] + [q])
        return real_commit(changes)

    store_commit = store.commit
    store.commit = racing_commit
    try:
        r = client.post("/api/questions", headers=ana, json={"text": "A mea", "category": "other"})
    finally:
        store.commit = store_commit
    assert r.status_code == 201 and calls["n"] == 2
    texts = sorted(q["text"] for q in fake.rows["questions"]["data"])
    assert texts == ["A mea", "De pe alt server"]
    assert sorted(q["text"] for q in client.get("/api/questions", headers=ana).json()) == texts


def test_supabase_failed_request_leaves_no_half_written_data(supa_db):
    fake = supa_db(rows={"users": {}})
    app_module.load_db()
    login("Ana")
    before = len(fake.writes)
    assert client.post("/api/questions", headers={"Authorization": "Bearer x"}, json={"text": "x"}).status_code == 401
    assert len(fake.writes) == before


def test_supabase_down_never_starts_empty(supa_db):
    fake = supa_db(down=True)
    with pytest.raises(RuntimeError):
        app_module.load_db()
    assert fake.writes == []


def test_serverless_without_supabase_says_what_is_missing(monkeypatch):
    monkeypatch.setattr(app_module, "SERVERLESS", True)
    monkeypatch.setenv("CUTIA_PERSIST", "1")
    r = client.get("/api/config", headers={"X-Lang": "en"})
    assert r.status_code == 503 and "SUPABASE_SECRET_KEY" in r.json()["detail"]
    assert client.get("/static/index.html").status_code == 200


def test_cron_digest_needs_cron_secret(monkeypatch):
    monkeypatch.setattr(app_module, "run_digest_in_background", lambda: calls.append(1))
    monkeypatch.setattr(app_module.digest, "due", lambda d: True)
    calls = []
    assert client.get("/api/cron/digest").status_code == 401             # fără CRON_SECRET pe server: nimeni
    monkeypatch.setenv("CRON_SECRET", "secret-cron-123")
    assert client.get("/api/cron/digest", headers={"Authorization": "Bearer gresit"}).status_code == 401
    assert client.get("/api/cron/digest", headers={"Authorization": "Bearer secret-cron-123"}).json() == {"ok": True}
    assert calls == [1]


def test_files_go_to_private_bucket(supa_db):
    fake = supa_db(rows={"users": {}})
    app_module.load_db()
    h = login("Ana")
    sid = client.post("/api/showcase", headers=h, data={"title": "X", "live_url": "https://x.app"},
                      files={"image": ("s.png", PNG_1PX, "image/png")}).json()["id"]
    assert list(fake.files.values()) == [PNG_1PX]
    assert client.get(f"/api/showcase/{sid}/image", headers=login("Vlad")).content == PNG_1PX
    client.delete(f"/api/showcase/{sid}", headers=h)
    assert fake.files == {}


# ---------------------------------------------------------------- Aplicația combinată: FAQ cu acord, statusuri, CSV, limită AI, demo

def test_faq_needs_student_consent_and_revoking_removes_it():
    ha, hb, ht = login("Ana"), login("Vlad"), login("Radu", "trainer")
    qid = client.post("/api/questions", headers=ha, json={"text": "Cum leg un buton de o funcție?", "category": "other"}).json()["id"]
    client.post(f"/api/questions/{qid}/answer", headers=ht, json={"text": "Cu addEventListener."})
    # Fără acord: trainerul nu poate publica întrebarea în FAQ, nici direct, nici prin /api/faq
    assert client.post(f"/api/questions/{qid}/to-faq", headers=ht).status_code == 400
    assert client.post("/api/faq", headers=ht, json={"q": "x?x", "a": "y", "question_id": qid}).status_code == 400
    # Doar autorul își dă acordul; alt student nu poate, trainerul nici atât
    assert client.post(f"/api/questions/{qid}/faq-consent", headers=hb, json={"faq_ok": True}).status_code == 404
    assert client.post(f"/api/questions/{qid}/faq-consent", headers=ht, json={"faq_ok": True}).status_code == 403
    assert client.post(f"/api/questions/{qid}/faq-consent", headers=ha, json={"faq_ok": True}).json()["faq_ok"] is True
    f = client.post(f"/api/questions/{qid}/to-faq", headers=ht)
    assert f.status_code == 201 and "question_id" not in f.json()
    faq = client.get("/api/faq", headers=hb).json()
    assert faq[0]["q"] == "Cum leg un buton de o funcție?" and "Ana" not in _json.dumps(faq)
    # Studentul își retrage acordul: intrarea dispare din FAQ
    client.post(f"/api/questions/{qid}/faq-consent", headers=ha, json={"faq_ok": False})
    assert client.get("/api/faq", headers=hb).json() == []


def test_proposal_decision_is_trainer_only_and_syncs_chosen():
    ha, hb, ht = login("Ana"), login("Vlad"), login("Radu", "trainer")
    pid = client.post("/api/proposals", headers=ha, json={"title": "Bingo", "description": "Joc", "audience": "Clasa", "approved": True}).json()["id"]
    assert client.get("/api/proposals", headers=hb).json()[0]["decision"] == "new"
    # Studenții nu pot schimba statusul, nici pe propunerea lor
    assert client.post(f"/api/proposals/{pid}/decision", headers=ha, json={"decision": "chosen"}).status_code == 403
    assert client.post(f"/api/proposals/{pid}/decision", headers=ht, json={"decision": "hacked"}).status_code == 422
    r = client.post(f"/api/proposals/{pid}/decision", headers=ht, json={"decision": "discussing", "note": "Mai mic, te rog."}).json()
    assert r["decision"] == "discussing" and r["chosen"] is False
    seen = client.get("/api/proposals", headers=hb).json()[0]
    assert seen["trainer_note"] == "Mai mic, te rog." and seen["decision"] == "discussing"
    # „Aleasă” păstrează punctele și kitul de start ca înainte
    r = client.post(f"/api/proposals/{pid}/decision", headers=ht, json={"decision": "chosen"}).json()
    assert r["chosen"] is True and r["chosen_at"]
    assert any(e["kind"] == "chosen" for e in client.get("/api/points/me", headers=ha).json()["events"])
    r = client.post(f"/api/proposals/{pid}/decision", headers=ht, json={"decision": "rejected"}).json()
    assert r["chosen"] is False and r["decision"] == "rejected"
    # Butonul vechi „Alege” rămâne compatibil
    assert client.post(f"/api/proposals/{pid}/choose", headers=ht).json()["decision"] == "chosen"


def test_csv_export_trainer_only_and_formula_safe():
    ha, ht = login("Ana"), login("Radu", "trainer")
    client.post("/api/proposals", headers=ha, json={"title": "=HYPERLINK(\"x\")", "description": "Joc", "audience": "Clasa", "approved": True})
    assert client.get("/api/proposals/export.csv", headers=ha).status_code == 403
    r = client.get("/api/proposals/export.csv", headers=ht)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    body = r.content.decode("utf-8-sig")
    assert "'=HYPERLINK" in body and "titlu" in body.splitlines()[0]


def test_refine_daily_limit(monkeypatch):
    ha = login("Ana")
    monkeypatch.setattr(app_module, "REFINE_PER_DAY", 2)
    monkeypatch.setattr(app_module.ai, "available", lambda: True)
    monkeypatch.setattr(app_module.ai, "refine", lambda *a: {"title": "T", "description": "D", "audience": "A", "missing": [], "engine": "claude"})
    lefts = [client.post("/api/proposals/refine", headers=ha, json={"title": "x"}).json()["refines_left"] for _ in range(2)]
    assert lefts == [1, 0]
    r = client.post("/api/proposals/refine", headers=ha, json={"title": "x"})
    assert r.status_code == 429 and "2" in r.json()["detail"]
    # Limita e per student
    assert client.post("/api/proposals/refine", headers=login("Vlad"), json={"title": "x"}).status_code == 200


def test_demo_seed_creates_accounts_and_data():
    app_module.seed_demo()
    r = client.post("/api/login", json={"login": "trainer@demo.cutia", "password": app_module.DEMO_PASSWORD})
    assert r.status_code == 200 and r.json()["role"] == "trainer"
    ana = client.post("/api/login", json={"login": "ana", "password": app_module.DEMO_PASSWORD}).json()
    h = {"Authorization": f"Bearer {ana['token']}"}
    assert ana["role"] == "student" and len(client.get("/api/questions", headers=h).json()) == 2
    assert {p["decision"] for p in client.get("/api/proposals", headers=h).json()} == {"new", "discussing", "chosen"}
