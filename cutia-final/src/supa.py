"""
Conturi prin Supabase Auth (opțional).

Dacă pe server sunt setate SUPABASE_URL și SUPABASE_ANON_KEY, parolele nu mai
stau la noi: Supabase le păstrează, trimite emailurile de confirmare și de
resetare, iar Google merge prin Supabase. Noi doar verificăm pe server, la
fiecare intrare, tokenul primit de la Supabase (GET /auth/v1/user), apoi
deschidem o sesiune Cutia Clasei ca de obicei.

Vorbim direct cu API-ul REST al Supabase prin httpx, fără supabase-js în
browser (fără dependențe noi). Cheia `service_role` nu se folosește
niciodată: anon key ajunge, iar ea nu dă acces la date.
"""

import os
import time
from typing import Optional

import httpx

TIMEOUT = 10.0
_transport: Optional[httpx.BaseTransport] = None  # testele pun aici un server fals
_settings_cache = {"at": 0.0, "value": None}


class SupabaseError(Exception):
    """Eroare de la Supabase; `code` e scurt: invalid, unconfirmed, exists, weak, failed."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def url() -> str:
    return os.environ.get("SUPABASE_URL", "").strip().rstrip("/")


def anon_key() -> str:
    return os.environ.get("SUPABASE_ANON_KEY", "").strip()


def enabled() -> bool:
    return bool(url() and anon_key())


def _request(method: str, path: str, token: Optional[str] = None, **kwargs) -> httpx.Response:
    headers = {"apikey": anon_key(), "Authorization": f"Bearer {token or anon_key()}"}
    try:
        with httpx.Client(timeout=TIMEOUT, transport=_transport) as client:
            return client.request(method, f"{url()}/auth/v1{path}", headers=headers, **kwargs)
    except httpx.HTTPError:
        raise SupabaseError("failed")


def _error_code(res: httpx.Response) -> str:
    try:
        data = res.json()
    except ValueError:
        data = {}
    text = " ".join(str(data.get(k, "")) for k in ("code", "error_code", "error", "msg", "message", "error_description")).lower()
    if "not_confirmed" in text or "not confirmed" in text:
        return "unconfirmed"
    if "already" in text or "exists" in text:
        return "exists"
    if "weak" in text or "password should" in text:
        return "weak"
    if "invalid" in text or res.status_code in (400, 401):
        return "invalid"
    return "failed"


def settings() -> dict:
    """Ce e pornit în proiectul Supabase (Google? confirmare pe email?). Cache 5 minute."""
    if _settings_cache["value"] is not None and time.time() - _settings_cache["at"] < 300:
        return _settings_cache["value"]
    try:
        res = _request("GET", "/settings")
        value = res.json() if res.status_code == 200 else {}
    except (SupabaseError, ValueError):
        value = {}
    _settings_cache.update(at=time.time(), value=value)
    return value


def google_enabled() -> bool:
    return bool(settings().get("external", {}).get("google"))


def emails_are_verified() -> bool:
    """Doar dacă Supabase cere confirmarea emailului putem avea încredere că
    cineva chiar deține adresa (contează pentru TRAINER_EMAILS)."""
    s = settings()
    return bool(s) and s.get("mailer_autoconfirm") is False


def sign_up(email: str, password: str, name: str, redirect_to: str) -> Optional[str]:
    """Creează contul. Întoarce tokenul dacă intră direct, sau None dacă
    Supabase a trimis un email de confirmare."""
    res = _request("POST", "/signup", params={"redirect_to": redirect_to},
                   json={"email": email, "password": password, "data": {"name": name}})
    if res.status_code >= 400:
        raise SupabaseError(_error_code(res))
    return res.json().get("access_token")


def sign_in(email: str, password: str) -> str:
    res = _request("POST", "/token", params={"grant_type": "password"}, json={"email": email, "password": password})
    if res.status_code >= 400:
        raise SupabaseError(_error_code(res))
    token = res.json().get("access_token")
    if not token:
        raise SupabaseError("failed")
    return token


def get_user(token: str) -> dict:
    """Verifică tokenul la Supabase: nu ne încredem în ce scrie în el, întrebăm serverul lor."""
    res = _request("GET", "/user", token=token)
    if res.status_code != 200:
        raise SupabaseError("invalid")
    user = res.json()
    if not user.get("email") or not (user.get("email_confirmed_at") or user.get("confirmed_at")):
        raise SupabaseError("unconfirmed")
    return user


def recover(email: str, redirect_to: str):
    res = _request("POST", "/recover", params={"redirect_to": redirect_to}, json={"email": email})
    if res.status_code >= 500:
        raise SupabaseError("failed")


def update_password(token: str, password: str):
    res = _request("PUT", "/user", token=token, json={"password": password})
    if res.status_code >= 400:
        raise SupabaseError(_error_code(res))


def provider(user: dict) -> str:
    return (user.get("app_metadata") or {}).get("provider") or "email"


def display_name(user: dict) -> str:
    meta = user.get("user_metadata") or {}
    return (meta.get("name") or meta.get("full_name") or user["email"].split("@")[0]).strip()[:60]
