"""
Durable identity — Sprint 11 (G3·1, G3·2).

Two independent reasons a second process could not serve an authenticated
request:

  G3·1  JWTHandler fell back to a generated keypair when no key was
        configured, silently. Two uvicorn workers signed with different keys
        and rejected each other's tokens; a restart invalidated every session.
        The env vars it reads were documented nowhere, so nobody set them.

  G3·2  InMemoryUserRepository was the only implementation. Accounts lived in
        a per-process dict: a user registered against one worker did not exist
        for the next request served by another, and every account vanished on
        restart.

Password hashing moved from sha256_crypt to scrypt in the same change, so the
legacy-hash path is covered here too.
"""
from __future__ import annotations

import subprocess
import sys

import mongomock
import pytest
from passlib.context import CryptContext
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.infrastructure.auth.jwt_handler import (
    JWTHandler,
    TokenInvalidError,
    generate_test_key_pair,
)
from src.infrastructure.auth.user_repository import (
    InMemoryUserRepository,
    InvalidCredentialsError,
    MongoUserRepository,
    UserAlreadyExistsError,
    UserNotFoundError,
)


@pytest.fixture()
def keypair(tmp_path):
    private_pem, public_pem = generate_test_key_pair()
    priv = tmp_path / "jwt_private.pem"
    pub = tmp_path / "jwt_public.pem"
    priv.write_bytes(private_pem)
    pub.write_bytes(public_pem)
    return priv, pub, private_pem, public_pem


# A pre-migration hash, produced the way the old code produced it. Building it
# through the live context with scheme= is deprecated in passlib 1.7.
_LEGACY_CTX = CryptContext(schemes=["sha256_crypt"])


@pytest.fixture()
def repo():
    return MongoUserRepository(mongomock.MongoClient()["erp_rag"]["users"])


# ---------------------------------------------------------------------------
# G3·1 — shared signing keys
# ---------------------------------------------------------------------------

class TestSigningKeysAreShared:
    def test_without_configured_keys_two_handlers_disagree(self):
        """The defect, pinned: this is what two uvicorn workers did."""
        a, b = JWTHandler(), JWTHandler()
        token = a.issue(user_id="u", role="SUPER_ADMIN", tenant_id="t")

        with pytest.raises(TokenInvalidError):
            b.verify(token)

    def test_keys_from_files_make_two_handlers_agree(self, keypair, monkeypatch):
        priv, pub, _, _ = keypair
        monkeypatch.setenv("JWT_PRIVATE_KEY_PATH", str(priv))
        monkeypatch.setenv("JWT_PUBLIC_KEY_PATH", str(pub))
        monkeypatch.delenv("JWT_PRIVATE_KEY_PEM", raising=False)
        monkeypatch.delenv("JWT_PUBLIC_KEY_PEM", raising=False)

        a, b = JWTHandler(), JWTHandler()
        claims = b.verify(a.issue(user_id="u", role="SUPER_ADMIN", tenant_id="t"))

        assert claims.user_id == "u"
        assert claims.role == "SUPER_ADMIN"

    def test_inline_pem_also_works(self, keypair, monkeypatch):
        _, _, private_pem, public_pem = keypair
        monkeypatch.setenv("JWT_PRIVATE_KEY_PEM", private_pem.decode())
        monkeypatch.setenv("JWT_PUBLIC_KEY_PEM", public_pem.decode())

        a, b = JWTHandler(), JWTHandler()
        assert b.verify(a.issue(user_id="u", role="CRM_AGENT", tenant_id="t")).user_id == "u"

    def test_inline_pem_wins_over_path(self, keypair, monkeypatch, tmp_path):
        """Both set is ambiguous; the inline value is documented to win."""
        priv, pub, private_pem, public_pem = keypair
        other_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        (tmp_path / "other.pem").write_bytes(
            other_priv.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        monkeypatch.setenv("JWT_PRIVATE_KEY_PEM", private_pem.decode())
        monkeypatch.setenv("JWT_PUBLIC_KEY_PEM", public_pem.decode())
        monkeypatch.setenv("JWT_PRIVATE_KEY_PATH", str(tmp_path / "other.pem"))
        monkeypatch.setenv("JWT_PUBLIC_KEY_PATH", str(pub))

        token = JWTHandler().issue(user_id="u", role="CRM_AGENT", tenant_id="t")
        assert JWTHandler().verify(token).user_id == "u"

    def test_a_real_second_process_accepts_the_token(self, keypair, tmp_path):
        """The actual claim: a separate OS process, not a second object."""
        priv, pub, _, _ = keypair
        env_setup = (
            f"import os;"
            f"os.environ['JWT_PRIVATE_KEY_PATH']={str(priv)!r};"
            f"os.environ['JWT_PUBLIC_KEY_PATH']={str(pub)!r};"
        )
        issue = subprocess.run(
            [sys.executable, "-c", env_setup +
             "from src.infrastructure.auth.jwt_handler import JWTHandler;"
             "print(JWTHandler().issue(user_id='u', role='SUPER_ADMIN', tenant_id='t'))"],
            capture_output=True, text=True, timeout=120, cwd=".",
        )
        assert issue.returncode == 0, issue.stderr
        token = issue.stdout.strip().splitlines()[-1]

        verify = subprocess.run(
            [sys.executable, "-c", env_setup +
             "from src.infrastructure.auth.jwt_handler import JWTHandler;"
             f"print(JWTHandler().verify({token!r}).user_id)"],
            capture_output=True, text=True, timeout=120, cwd=".",
        )
        assert verify.returncode == 0, verify.stderr
        assert "u" in verify.stdout


# ---------------------------------------------------------------------------
# G3·2 — accounts that outlive the process
# ---------------------------------------------------------------------------

class TestMongoUserRepository:
    def test_a_second_repository_sees_the_account(self, repo):
        """Two processes share one collection; two dicts share nothing."""
        repo.create(username="alice", password="securepass1", role="FINANCE_MANAGER")

        second = MongoUserRepository(repo._col)
        assert second.get_by_username("alice").role == "FINANCE_MANAGER"

    def test_login_works_from_a_second_repository(self, repo):
        repo.create(username="alice", password="securepass1")

        record = MongoUserRepository(repo._col).verify_password("alice", "securepass1")
        assert record.username == "alice"

    def test_duplicate_username_is_rejected(self, repo):
        repo.create(username="alice", password="securepass1")

        with pytest.raises(UserAlreadyExistsError):
            repo.create(username="alice", password="otherpass1")

    def test_wrong_password_is_rejected(self, repo):
        repo.create(username="alice", password="securepass1")

        with pytest.raises(InvalidCredentialsError):
            repo.verify_password("alice", "wrongpass1")

    def test_unknown_user_raises_the_same_error_as_a_wrong_password(self, repo):
        """Distinguishable errors would let a caller enumerate usernames."""
        with pytest.raises(InvalidCredentialsError):
            repo.verify_password("nobody", "securepass1")

    def test_password_reset_round_trip(self, repo):
        repo.create(username="alice", password="securepass1")
        repo.save_reset_token("alice", "tok-123")

        repo.reset_password("tok-123", "brandnewpass1")

        assert repo.verify_password("alice", "brandnewpass1").username == "alice"
        with pytest.raises(InvalidCredentialsError):
            repo.verify_password("alice", "securepass1")

    def test_reset_token_is_cleared_after_use(self, repo):
        repo.create(username="alice", password="securepass1")
        repo.save_reset_token("alice", "tok-123")
        repo.reset_password("tok-123", "brandnewpass1")

        with pytest.raises(UserNotFoundError):
            repo.reset_password("tok-123", "thirdpass123")

    def test_reset_token_for_unknown_user_raises(self, repo):
        with pytest.raises(UserNotFoundError):
            repo.save_reset_token("nobody", "tok-123")

    def test_password_is_not_stored_in_clear(self, repo):
        repo.create(username="alice", password="securepass1")

        doc = repo._col.find_one({"username": "alice"})
        assert "securepass1" not in str(doc)


# ---------------------------------------------------------------------------
# Hash migration
# ---------------------------------------------------------------------------

class TestPasswordHashing:
    def test_new_passwords_use_scrypt(self, repo):
        repo.create(username="alice", password="securepass1")

        assert repo._col.find_one({"username": "alice"})["hashed_password"].startswith(
            "$scrypt$"
        )

    @pytest.mark.parametrize("repo_kind", ["mongo", "memory"])
    def test_legacy_sha256_hashes_still_log_in(self, repo, repo_kind):
        """Accounts created before this change must not be locked out."""
        legacy = _LEGACY_CTX.hash("securepass1")

        if repo_kind == "mongo":
            store = repo
            store._col.insert_one({
                "user_id": "u1", "username": "bob", "hashed_password": legacy,
                "role": "REPORTING_ANALYST", "tenant_id": "t", "reset_token": None,
            })
        else:
            store = InMemoryUserRepository()
            store.create(username="bob", password="placeholder1")
            store.get_by_username("bob").hashed_password = legacy

        assert store.verify_password("bob", "securepass1").username == "bob"

    def test_legacy_hash_is_upgraded_on_successful_login(self, repo):
        """The old digests drain away without a migration or a forced reset."""
        legacy = _LEGACY_CTX.hash("securepass1")
        repo._col.insert_one({
            "user_id": "u1", "username": "bob", "hashed_password": legacy,
            "role": "REPORTING_ANALYST", "tenant_id": "t", "reset_token": None,
        })

        repo.verify_password("bob", "securepass1")

        stored = repo._col.find_one({"username": "bob"})["hashed_password"]
        assert stored.startswith("$scrypt$")
        assert stored != legacy
