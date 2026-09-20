"""
services/password_service.py
Royal Metal Allocation System — Python port

Password hashing. Never store, log, or compare a plaintext password
anywhere else in the codebase — always go through these two functions.
bcrypt handles salting internally; `checkpw` is constant-time.
"""

import bcrypt


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
