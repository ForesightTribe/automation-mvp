from cryptography.fernet import Fernet
from app.core.config import settings


def _cipher() -> Fernet:
    return Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt(plain_text: str) -> str:
    return _cipher().encrypt(plain_text.encode()).decode()


def decrypt(cipher_text: str) -> str:
    return _cipher().decrypt(cipher_text.encode()).decode()


def generate_key() -> str:
    """Run once to generate ENCRYPTION_KEY for .env"""
    return Fernet.generate_key().decode()
