"""Runtime and dependency-free frozen-backup account validation parity."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from argon2 import PasswordHasher

from case_intelligence.local_account_format import parse_accounts, validate_password_hash
from case_intelligence.local_accounts import LocalAccountRepository, _parse


@pytest.fixture
def payload(tmp_path):
    repo = LocalAccountRepository(tmp_path / "accounts/local-accounts.json")
    repo.initialize("synthetic.admin", "Synthetic Administrator", "synthetic-format-password", actor="synthetic-operator")
    return json.loads(repo.path.read_bytes())


@pytest.mark.parametrize("version", [1, 2])
def test_shared_and_runtime_parsers_preserve_supported_accounts(payload, version):
    payload["format_version"] = version
    if version == 1:
        payload["accounts"][0].pop("session_revision")
    assert parse_accounts(payload) == _parse(payload)
    account = _parse(payload)[1]["synthetic.admin"]
    assert PasswordHasher().verify(account.password_hash, "synthetic-format-password")


@pytest.mark.parametrize("display_name", ["Synthetic\u202eReviewer", "Synthetic\x7fReviewer"])
def test_runtime_and_backup_reject_display_names_unsupported_by_principals(payload, display_name):
    payload["accounts"][0]["display_name"] = display_name
    for parse in (parse_accounts, _parse):
        with pytest.raises(RuntimeError, match="Display name"):
            parse(payload)


@pytest.mark.parametrize("encoded", [
    "$argon2id$v=19$m=0,t=0,p=0$c3ludGhldGlj$c3ludGhldGlj",
    "$argon2id$v=19$m=7,t=1,p=1$c3ludGhldGlj$c3ludGhldGlj",
    "$argon2id$v=19$m=65536,t=-1,p=1$c3ludGhldGlj$c3ludGhldGlj",
    "$argon2id$v=19$m=65536,t=1,p=0$c3ludGhldGlj$c3ludGhldGlj",
    "$argon2id$v=99$m=65536,t=1,p=1$c3ludGhldGlj$c3ludGhldGlj",
    "$argon2i$v=19$m=65536,t=1,p=1$c3ludGhldGlj$c3ludGhldGlj",
    "$argon2id$v=19$m=65536,t=1,p=1$!$!",
    "$argon2id$v=19$m=65536,t=1,p=1$A$c3ludGhldGlj",
    "$argon2id$v=19$m=65536,t=1,p=1$c2FsdA$c3ludGhldGlj",
    "$argon2id$v=19$m=65536,t=1,p=1$c3ludGhldGlj$YQ",
    "$argon2id$v=19$m=65536,t=1,p=1$c3ludGhldGlj$c3ludGhldGlk====",
])
def test_runtime_and_backup_reject_invalid_argon2_encodings_and_parameters(payload, encoded):
    payload["accounts"][0]["password_hash"] = encoded
    for parse in (parse_accounts, _parse):
        with pytest.raises(RuntimeError):
            parse(payload)


def test_legacy_phc_encoding_without_version_remains_structurally_readable(payload):
    encoded = payload["accounts"][0]["password_hash"].replace("$v=19", "")
    validate_password_hash(encoded)
    payload["accounts"][0]["password_hash"] = encoded
    assert parse_accounts(payload) == _parse(payload)


def test_frozen_validator_runs_with_only_stdlib_and_ignores_pythonpath(tmp_path):
    repo = LocalAccountRepository(tmp_path / "accounts/local-accounts.json")
    repo.initialize("synthetic.admin", "Synthetic Administrator", "synthetic-format-password", actor="synthetic-operator")
    hostile = tmp_path / "ambient-modules"
    hostile.mkdir()
    (hostile / "dataclasses.py").write_text('raise RuntimeError("ambient import must not run")\n')
    validator = Path(__file__).parents[1] / "src/case_intelligence/local_account_format.py"
    result = subprocess.run([sys.executable, "-I", "-S", str(validator), str(repo.path)],
                            env={**os.environ, "PYTHONPATH": str(hostile)}, capture_output=True, text=True)
    assert result.returncode == 0 and not result.stdout and not result.stderr


@pytest.mark.parametrize("explicit_version", [False, True])
def test_legacy_argon2id_version_16_authenticates_with_shared_validation(payload, explicit_version):
    from argon2.low_level import Type, hash_secret
    encoded = hash_secret(b"synthetic-format-password", b"synthetic-salt-16", time_cost=1,
                          memory_cost=32, parallelism=1, hash_len=16, type=Type.ID, version=16).decode()
    if not explicit_version:
        encoded = encoded.replace("$v=16", "")
    payload["accounts"][0]["password_hash"] = encoded
    assert parse_accounts(payload) == _parse(payload)
    assert PasswordHasher().verify(encoded, "synthetic-format-password")
