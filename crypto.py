"""AES-256 encryption for sensitive fields"""
import os, base64, json
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_FILE = os.path.join(os.path.dirname(__file__), ".sige_key")

def _get_key() -> bytes:
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return base64.b64decode(f.read())
    key = os.urandom(32)  # 256 bits
    with open(KEY_FILE, "wb") as f:
        f.write(base64.b64encode(key))
    os.chmod(KEY_FILE, 0o600)
    return key

_KEY = _get_key()

def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    aesgcm = AESGCM(_KEY)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()

def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        data = base64.b64decode(token.encode())
        nonce, ct = data[:12], data[12:]
        aesgcm = AESGCM(_KEY)
        return aesgcm.decrypt(nonce, ct, None).decode()
    except Exception:
        return "[ERROR_DECRYPT]"
