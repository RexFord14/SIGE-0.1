"""Encriptación AES-256 para campos sensibles."""
import base64
import hashlib
from cryptography.fernet import Fernet
from config import AES_KEY_HEX

# Derivar clave Fernet de 32 bytes desde la clave hex configurada
_raw_key = bytes.fromhex(AES_KEY_HEX)[:32]
_fernet_key = base64.urlsafe_b64encode(_raw_key)
_fernet = Fernet(_fernet_key)


def encrypt_value(plaintext: str) -> str:
    """Encripta un valor con AES-256 (Fernet)."""
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """Desencripta un valor AES-256."""
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except Exception:
        return ciphertext  # Si no está encriptado, devolver tal cual


def hash_value(value: str) -> str:
    """Hash SHA-256 para búsqueda sin exponer el valor original."""
    return hashlib.sha256(value.strip().upper().encode()).hexdigest()
