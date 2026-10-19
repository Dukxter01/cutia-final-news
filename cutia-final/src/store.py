"""
Datele aplicației în Supabase: Postgres pentru date, Storage pentru fișiere.

Cum funcționează (merge și pe Vercel, unde rulează mai multe copii ale serverului):
- aplicația lucrează cu `db` în memorie (rapid și simplu);
- fiecare colecție (questions, submissions, proposals, …) e un rând în tabelul
  `cutia_state`, cu un număr de versiune;
- la începutul fiecărei cereri luăm din Supabase DOAR colecțiile care s-au
  schimbat (`cutia_sync`), iar la final scriem DOAR ce am schimbat noi
  (`cutia_commit`), cu versiunea pe care am citit-o. Dacă altă copie a scris
  între timp, Supabase refuză, iar app.py reia cererea pe datele noi.
  Așa nu se pierde nimic, chiar dacă doi studenți scriu în același timp.
- fișierele încărcate stau în bucket-ul privat `cutia-files`.

Securitate: tabelul are Row Level Security pornit și NICIO politică, iar funcțiile
se pot rula doar cu cheia secretă. Serverul folosește `SUPABASE_SECRET_KEY`, care
stă doar în variabilele de mediu ale serverului, niciodată în browser sau pe GitHub.

Pornire: rulează o dată `supabase/schema.sql` în Supabase → SQL Editor.
Mutarea datelor existente:  python -m src.store migrate
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

import httpx

TABLE = "cutia_state"
BUCKET = "cutia-files"
TIMEOUT = 15.0
_transport: Optional[httpx.BaseTransport] = None  # testele pun aici un Supabase fals


class StoreError(Exception):
    pass


def url() -> str:
    return os.environ.get("SUPABASE_URL", "").strip().rstrip("/")


def secret() -> str:
    return os.environ.get("SUPABASE_SECRET_KEY", "").strip()


def enabled() -> bool:
    return bool(url() and secret())


def _headers(extra: Optional[dict] = None) -> dict:
    key = secret()
    headers = {"apikey": key}
    if key.startswith("eyJ"):  # cheia veche service_role (JWT) merge și ca Bearer; cheile noi sb_secret_ doar ca apikey
        headers["Authorization"] = f"Bearer {key}"
    headers.update(extra or {})
    return headers


_client: Optional[httpx.Client] = None


def _http() -> httpx.Client:
    # O singură conexiune refolosită: pe Vercel fiecare cerere vorbește cu Supabase de 1-2 ori
    global _client
    if _client is None or _transport is not None:
        _client = httpx.Client(timeout=TIMEOUT, transport=_transport)
    return _client


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    try:
        return _http().request(method, url() + path, **kwargs)
    except httpx.HTTPError as exc:
        raise StoreError(type(exc).__name__)


def _rpc(name: str, payload: dict):
    res = _request("POST", f"/rest/v1/rpc/{name}", json=payload,
                   headers=_headers({"Content-Type": "application/json"}))
    if res.status_code != 200:
        raise StoreError(f"{name} {res.status_code}: {res.text[:200]}")
    return res.json()


# ---------------------------------------------------------------- date (Postgres prin PostgREST)

def sync(known: dict) -> list:
    """Versiunea fiecărei colecții + datele doar pentru cele care diferă de `known`.
    Întoarce [{name, version, changed, data}]. Ridică StoreError dacă Supabase nu răspunde."""
    return _rpc("cutia_sync", {"known": known})


def commit(changes: list) -> dict:
    """Scrie colecțiile schimbate, doar dacă versiunile din Supabase sunt cele citite de noi.
    changes = [{name, version, data}] → {"ok": true, "versions": {...}} sau {"ok": false, "conflict": [...]}."""
    return _rpc("cutia_commit", {"changes": changes})


def load() -> dict:
    """Toate colecțiile (folosit la mutarea datelor)."""
    return {row["name"]: row["data"] for row in sync({})}


# ---------------------------------------------------------------- fișiere (Storage, bucket privat)

def put_file(name: str, content: bytes):
    res = _request("POST", f"/storage/v1/object/{BUCKET}/{name}", content=content,
                   headers=_headers({"Content-Type": "application/octet-stream", "x-upsert": "true"}))
    if res.status_code >= 300:
        raise StoreError(f"upload {res.status_code}: {res.text[:200]}")


def get_file(name: str) -> Optional[bytes]:
    res = _request("GET", f"/storage/v1/object/{BUCKET}/{name}", headers=_headers())
    if res.status_code == 200:
        return res.content
    if res.status_code in (400, 404):
        return None
    raise StoreError(f"download {res.status_code}")


def delete_file(name: str):
    _request("DELETE", f"/storage/v1/object/{BUCKET}/{name}", headers=_headers())


# ---------------------------------------------------------------- mutarea datelor locale în Supabase

def migrate(data_file: Path, upload_dir: Path):
    if not enabled():
        sys.exit("Setează întâi SUPABASE_URL și SUPABASE_SECRET_KEY (în .env).")
    existing = sync({})
    if any(row["name"] == "users" and row["data"] for row in existing):
        sys.exit("În Supabase există deja date. Nu le suprascriu.")
    versions = {row["name"]: row["version"] for row in existing}
    data = json.loads(data_file.read_text(encoding="utf-8")) if data_file.exists() else {}
    if data:
        res = commit([{"name": k, "version": versions.get(k, 0), "data": v} for k, v in data.items()])
        if not res.get("ok"):
            sys.exit(f"Nu am putut scrie: {res}")
        print(f"✓ Date mutate: {', '.join(f'{k} ({len(v)})' for k, v in data.items() if isinstance(v, (list, dict)))}")
    files = [p for p in upload_dir.glob("*") if p.is_file()] if upload_dir.exists() else []
    for p in files:
        put_file(p.name, p.read_bytes())
    print(f"✓ Fișiere mutate: {len(files)}")


def _read_env(path: Path):
    for line in (path.read_text(encoding="utf-8").splitlines() if path.exists() else []):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if __name__ == "__main__":
    if sys.argv[1:] == ["migrate"]:
        root = Path(__file__).resolve().parent.parent
        _read_env(root / ".env")
        data_file = Path(os.environ.get("CUTIA_DATA", root / "data" / "cutia.json"))
        migrate(data_file, Path(os.environ.get("CUTIA_UPLOADS", data_file.parent / "uploads")))
    else:
        print("Folosire: python -m src.store migrate")
