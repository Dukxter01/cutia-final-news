"""
Datele aplicației în Supabase (opțional): Postgres pentru date, Storage pentru fișiere.

Cum funcționează:
- aplicația lucrează în continuare cu `db` în memorie (rapid și simplu);
- fiecare colecție (questions, submissions, proposals, …) e un rând în tabelul
  `cutia_state`; după fiecare schimbare scriem în fundal DOAR colecțiile
  schimbate (în ~1 secundă), iar la oprirea serverului scriem tot ce a rămas;
- fișierele încărcate stau în bucket-ul privat `cutia-files`.

Securitate: tabelul are Row Level Security pornit și NICIO politică, deci cheia
publică (anon) din browser nu poate citi nimic. Serverul folosește cheia secretă
(`SUPABASE_SECRET_KEY`), care stă doar în variabilele de mediu ale serverului,
niciodată în browser sau pe GitHub. Accesul la date îl verifică tot app.py.

Pornire: rulează o dată `supabase/schema.sql` în Supabase → SQL Editor.
Mutarea datelor existente:  python -m src.store migrate
"""

import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import httpx

TABLE = "cutia_state"
BUCKET = "cutia-files"
TIMEOUT = 15.0
FLUSH_EVERY = 1.0
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


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    try:
        with httpx.Client(timeout=TIMEOUT, transport=_transport) as client:
            return client.request(method, url() + path, **kwargs)
    except httpx.HTTPError as exc:
        raise StoreError(type(exc).__name__)


# ---------------------------------------------------------------- date (Postgres prin PostgREST)

def load() -> dict:
    """Toate colecțiile. Ridică StoreError dacă Supabase nu răspunde (nu pornim cu date goale)."""
    res = _request("GET", f"/rest/v1/{TABLE}?select=name,data", headers=_headers())
    if res.status_code != 200:
        raise StoreError(f"load {res.status_code}: {res.text[:200]}")
    return {row["name"]: row["data"] for row in res.json()}


def save(collections: dict):
    """Scrie (upsert) colecțiile primite, câte un rând fiecare."""
    rows = [{"name": k, "data": v, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())} for k, v in collections.items()]
    res = _request("POST", f"/rest/v1/{TABLE}?on_conflict=name", json=rows,
                   headers=_headers({"Prefer": "resolution=merge-duplicates,return=minimal", "Content-Type": "application/json"}))
    if res.status_code >= 300:
        raise StoreError(f"save {res.status_code}: {res.text[:200]}")


class Writer:
    """Scrie în fundal doar colecțiile care s-au schimbat de la ultima scriere."""

    def __init__(self, db: dict, lock):
        self.db, self.lock = db, lock
        self.hashes: dict = {}
        self.dirty = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.last_error: Optional[str] = None

    def remember(self):
        """După încărcare: ce e deja în Supabase nu trebuie rescris."""
        with self.lock:
            self.hashes = {k: self._hash(v) for k, v in self.db.items()}

    @staticmethod
    def _hash(value) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

    def mark(self):
        self.dirty.set()
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()

    def _loop(self):
        while True:
            self.dirty.wait()
            time.sleep(FLUSH_EVERY)  # adunăm schimbările dintr-o secundă într-o singură scriere
            self.flush()

    def flush(self):
        self.dirty.clear()
        with self.lock:  # copiem sub lacăt, trimitem fără lacăt
            snapshot = {k: json.loads(json.dumps(v, default=str)) for k, v in self.db.items()}
        changed = {k: v for k, v in snapshot.items() if self.hashes.get(k) != self._hash(v)}
        if not changed:
            return
        try:
            save(changed)
            self.hashes.update({k: self._hash(v) for k, v in changed.items()})
            self.last_error = None
        except StoreError as err:
            self.last_error = str(err)
            self.dirty.set()  # reîncercăm la tura următoare
            time.sleep(5)


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
    existing = load()
    if existing.get("users"):
        sys.exit("În Supabase există deja date. Nu le suprascriu.")
    data = json.loads(data_file.read_text(encoding="utf-8")) if data_file.exists() else {}
    if data:
        save(data)
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
