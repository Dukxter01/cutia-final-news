"""
„Verifică repo-ul” înainte de predare.

Citește un repo public de pe GitHub și verifică lista „Gata când” a
trainerului: README cu secțiunile cerute, .env ignorat de git, niciun .env
urcat, nicio cheie API în cod sau în ultimele commituri, link live.

Vorbim doar cu api.github.com și raw.githubusercontent.com (adrese fixe),
iar owner/repo sunt validate strict, deci serverul nu poate fi folosit ca să
citească alte adrese. Cheile găsite se arată mascate, niciodată întregi.
"""

import base64
import json
import os
import re
import time
from typing import Optional
from urllib.parse import quote

import httpx

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
TIMEOUT = 10.0
_transport: Optional[httpx.BaseTransport] = None  # testele pun aici un GitHub fals
_cache: dict = {}  # (repo, sha) -> rezultat, ca să nu consumăm limita GitHub de două ori
CACHE_SECONDS = 3600

REPO_RE = re.compile(r"^https?://(?:www\.)?github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100})/?(?:[?#].*)?$")
KEY_PATTERNS = [
    ("Anthropic", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI", re.compile(r"sk-(?!ant-)(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    ("Google", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("GitHub", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("Supabase secret", re.compile(r"sb_secret_[A-Za-z0-9_\-]{20,}")),
    ("AWS", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Stripe", re.compile(r"sk_live_[0-9a-zA-Z]{24,}")),
]
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.(eyJ[A-Za-z0-9_\-]{10,})\.[A-Za-z0-9_\-]{10,}")
TEXT_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json", ".html", ".css", ".md", ".txt", ".yml",
            ".yaml", ".toml", ".ini", ".cfg", ".env", ".sh", ".ipynb", ".vue", ".svelte", ".sql", ".rb", ".go", ".java"}
MAX_FILES = 80
MAX_FILE_BYTES = 300_000
ENV_FILE_RE = re.compile(r"(^|/)\.env(\.[^/]+)?$")
ENV_OK = (".env.example", ".env.sample", ".env.template")

# Secțiunile cerute în README (fișa trainerului), în toate limbile clasei
README_SECTIONS = {
    "what": ("ce face", "what it does", "what does", "about", "despre", "description", "descriere", "fonctionnalit", "cosa fa", "qué hace", "was macht", "overview"),
    "run": ("cum se pornește", "cum pornești", "how to run", "getting started", "install", "usage", "run locally", "npm ", "pip install",
            "uvicorn", "lancer", "avviare", "ejecutar", "starten"),
    "extras": ("funcții în plus", "extra", "features", "funcționalități", "bonus", "fonctionnalités", "funzionalità", "funciones", "funktionen"),
}


class RepoError(Exception):
    """not_github, not_found, github_busy, github_down"""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def parse_url(url: str) -> tuple:
    m = REPO_RE.match((url or "").strip())
    if not m:
        raise RepoError("not_github")
    owner, repo = m.group(1), m.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


def _client() -> httpx.Client:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "CutiaClasei/1.0"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:  # doar citire pe repo-uri publice; ridică limita de la 60 la 5000 de cereri pe oră
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(timeout=TIMEOUT, transport=_transport, headers=headers, follow_redirects=False)


def _get(client, url: str):
    try:
        res = client.get(url)
    except httpx.HTTPError:
        raise RepoError("github_down")
    if res.status_code == 404:
        return None
    if res.status_code in (403, 429):
        raise RepoError("github_busy")
    if res.status_code >= 400:
        raise RepoError("github_down")
    return res


def mask(secret: str) -> str:
    return secret[:6] + "…" + secret[-3:] if len(secret) > 12 else "…"


def find_keys(text: str) -> list:
    """Întoarce [(tip, cheie mascată)] pentru tot ce seamănă a cheie secretă."""
    found = []
    for kind, pattern in KEY_PATTERNS:
        for m in pattern.finditer(text):
            found.append((kind, mask(m.group(0))))
    for m in JWT_RE.finditer(text):
        try:
            payload = m.group(1) + "=" * (-len(m.group(1)) % 4)
            if json.loads(base64.urlsafe_b64decode(payload)).get("role") == "service_role":
                found.append(("Supabase service_role", mask(m.group(0))))
        except (ValueError, json.JSONDecodeError, AttributeError):
            pass
    return found


def _is_text(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    return ext in TEXT_EXT or name.startswith(".env") or name in ("dockerfile", "procfile", "makefile")


def _readme_checks(text: str) -> dict:
    low = text.lower()
    out = {key: any(w in low for w in words) for key, words in README_SECTIONS.items()}
    links = [u for u in re.findall(r"https?://[^\s)>\]\"']+", text) if "github.com" not in u and "localhost" not in u
             and "127.0.0.1" not in u and "shields.io" not in u]
    out["live"] = links[0] if links else None
    return out


def check(url: str) -> dict:
    owner, repo = parse_url(url)
    with _client() as client:
        info = _get(client, f"{API}/repos/{owner}/{repo}")
        if info is None:
            raise RepoError("not_found")  # nu există sau e privat
        info = info.json()
        branch = info.get("default_branch") or "main"
        head = _get(client, f"{API}/repos/{owner}/{repo}/commits/{quote(branch)}")
        sha = head.json()["sha"] if head is not None else branch
        cached = _cache.get((owner.lower(), repo.lower(), sha))
        if cached and time.time() - cached["at"] < CACHE_SECONDS:
            return cached["result"]

        tree_res = _get(client, f"{API}/repos/{owner}/{repo}/git/trees/{quote(sha)}?recursive=1")
        tree = [t for t in (tree_res.json().get("tree", []) if tree_res is not None else []) if t.get("type") == "blob"]
        paths = [t["path"] for t in tree]

        def raw(path):
            res = _get(client, f"{RAW}/{owner}/{repo}/{quote(sha)}/{quote(path)}")
            return res.text if res is not None else ""

        checks = []
        readme_path = next((p for p in paths if p.lower() in ("readme.md", "readme", "readme.txt", "readme.rst")), None)
        readme = raw(readme_path) if readme_path else ""
        r = _readme_checks(readme) if readme else {"what": False, "run": False, "extras": False, "live": None}
        checks.append({"key": "readme", "status": "ok" if readme_path else "fail"})
        for key in ("what", "run", "extras"):
            checks.append({"key": f"readme_{key}", "status": "ok" if r[key] else "warn"})
        checks.append({"key": "live_link", "status": "ok" if r["live"] else "warn", "detail": r["live"]})

        gitignore = raw(".gitignore") if ".gitignore" in paths else ""
        ignore_lines = {line.strip() for line in gitignore.splitlines()}
        ignores_env = bool(ignore_lines & {".env", "/.env", ".env*", "*.env", ".env.*", "**/.env", ".env.local"})
        checks.append({"key": "gitignore_env", "status": "ok" if ignores_env else "fail"})

        env_files = [p for p in paths if ENV_FILE_RE.search(p) and not p.endswith(ENV_OK)]
        checks.append({"key": "no_env_file", "status": "fail" if env_files else "ok", "detail": env_files[:5]})

        # Cheile din fișierele de acum
        now_found = []
        for t in [t for t in tree if _is_text(t["path"]) and t.get("size", 0) <= MAX_FILE_BYTES][:MAX_FILES]:
            for kind, masked in find_keys(raw(t["path"])):
                now_found.append({"file": t["path"], "kind": kind, "masked": masked})
        checks.append({"key": "no_keys_now", "status": "fail" if now_found else "ok", "detail": now_found[:10]})

        # Cheile din istoric: o cheie ștearsă din cod rămâne în commiturile vechi
        history = []
        limit = 30 if os.environ.get("GITHUB_TOKEN") else 8
        commits = _get(client, f"{API}/repos/{owner}/{repo}/commits?sha={quote(sha)}&per_page={limit}")
        scanned = 0
        for c in (commits.json() if commits is not None else [])[:limit]:
            detail = _get(client, f"{API}/repos/{owner}/{repo}/commits/{c['sha']}")
            scanned += 1
            for f in (detail.json().get("files", []) if detail is not None else []):
                added = "\n".join(line[1:] for line in (f.get("patch") or "").splitlines() if line.startswith("+"))
                for kind, masked in find_keys(added):
                    history.append({"commit": c["sha"][:7], "file": f.get("filename", ""), "kind": kind, "masked": masked})
        checks.append({"key": "no_keys_history", "status": "fail" if history else "ok", "detail": history[:10], "scanned": scanned})

        checks.append({"key": "trainer_access", "status": "manual"})

    result = {
        "repo": f"{owner}/{repo}", "url": f"https://github.com/{owner}/{repo}", "head": sha[:7],
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checks": checks,
        "passed": sum(c["status"] == "ok" for c in checks),
        "total": sum(c["status"] != "manual" for c in checks),
    }
    _cache[(owner.lower(), repo.lower(), sha)] = {"at": time.time(), "result": result}
    return result
