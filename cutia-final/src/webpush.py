"""
Notificări push pe telefon și calculator (Web Push), fără servicii externe.

Standardele folosite:
- RFC 8291 + RFC 8188 (aes128gcm): mesajul e criptat pentru browserul
  care s-a abonat, deci serviciul de push (Google, Apple, Mozilla) nu-l
  poate citi;
- RFC 8292 (VAPID): semnăm cererea cu cheia serverului, ca browserul să
  știe că notificarea vine de la noi.

Cheile VAPID se generează o singură dată:  python -m src.webpush
Cheia privată stă doar pe server (VAPID_PRIVATE_KEY), ca orice secret.
"""

import base64
import json
import os
import struct
import time
from typing import Optional
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

TIMEOUT = 10.0
_transport: Optional[httpx.BaseTransport] = None  # testele pun aici un serviciu de push fals


class Gone(Exception):
    """Abonamentul nu mai există (browser dezinstalat, permisiune retrasă): îl ștergem."""


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def public_key() -> str:
    return os.environ.get("VAPID_PUBLIC_KEY", "").strip()


def enabled() -> bool:
    return bool(public_key() and os.environ.get("VAPID_PRIVATE_KEY", "").strip())


def _private():
    d = int.from_bytes(unb64u(os.environ["VAPID_PRIVATE_KEY"].strip()), "big")
    return ec.derive_private_key(d, ec.SECP256R1())


def _raw_public(key) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def generate_keys() -> tuple:
    key = ec.generate_private_key(ec.SECP256R1())
    d = key.private_numbers().private_value.to_bytes(32, "big")
    return b64u(_raw_public(key)), b64u(d)


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(payload: bytes, p256dh: str, auth: str) -> bytes:
    """Criptează mesajul pentru un abonament (RFC 8291, aes128gcm, o singură înregistrare)."""
    ua_public = unb64u(p256dh)
    auth_secret = unb64u(auth)
    as_key = ec.generate_private_key(ec.SECP256R1())
    as_public = _raw_public(as_key)
    shared = as_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    salt = os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack("!IB", 4096, len(as_public)) + as_public + ciphertext


def vapid_header(endpoint: str) -> str:
    url = urlparse(endpoint)
    claims = {"aud": f"{url.scheme}://{url.netloc}", "exp": int(time.time()) + 12 * 3600,
              "sub": os.environ.get("VAPID_SUBJECT", "mailto:trainer@example.com")}
    signing_input = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}).encode()) + "." + b64u(json.dumps(claims).encode())
    key = _private()
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    jwt = signing_input + "." + b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={jwt}, k={b64u(_raw_public(key))}"


def send(subscription: dict, message: dict):
    """Trimite o notificare. Ridică Gone dacă abonamentul a expirat."""
    body = encrypt(json.dumps(message, ensure_ascii=False).encode(), subscription["keys"]["p256dh"], subscription["keys"]["auth"])
    headers = {"Authorization": vapid_header(subscription["endpoint"]), "Content-Encoding": "aes128gcm",
               "Content-Type": "application/octet-stream", "TTL": "86400", "Urgency": "normal"}
    try:
        with httpx.Client(timeout=TIMEOUT, transport=_transport) as client:
            res = client.post(subscription["endpoint"], content=body, headers=headers)
    except httpx.HTTPError:
        return
    if res.status_code in (404, 410):
        raise Gone()


if __name__ == "__main__":
    pub, priv = generate_keys()
    print("Pune în .env (sau în Render → Environment):\n")
    print(f"VAPID_PUBLIC_KEY={pub}")
    print(f"VAPID_PRIVATE_KEY={priv}")
    print("VAPID_SUBJECT=mailto:emailul-tau@exemplu.ro")
