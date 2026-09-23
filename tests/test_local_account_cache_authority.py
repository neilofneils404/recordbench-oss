"""Exercise cache authority with the actual atomic account writer."""
from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest

from case_intelligence.identity import LocalAuthenticationError
from case_intelligence.local_accounts import LocalAccountRepository
from tests.test_local_account_lifecycle import ACTOR, PASSWORD, identity, repository


def _change_accounts(path, operation):
    writer = LocalAccountRepository(Path(path))
    # Do not sleep between replacements or refresh any reader between removal
    # and restoration. The final file has the original size in every case.
    if operation == "password":
        writer.change_password("alice.admin", "synthetic-updated-password", actor=ACTOR)
    elif operation == "disable-enable":
        writer.set_enabled("alice.admin", False, actor=ACTOR)
        writer.set_enabled("alice.admin", True, actor=ACTOR)
    else:
        writer.set_administrator("alice.admin", False, actor=ACTOR)
        writer.set_administrator("alice.admin", True, actor=ACTOR)


@pytest.mark.parametrize("operation", ["password", "disable-enable", "demote-promote"])
@pytest.mark.parametrize("independent_process", [False, True])
def test_same_size_actual_writer_replacement_denies_each_cached_session(
    tmp_path, operation, independent_process,
):
    writer = repository(tmp_path)
    writer.create("backup.admin", "Backup Administrator", PASSWORD, administrator=True, actor=ACTOR)
    services = [identity(tmp_path, writer), identity(tmp_path, writer)]
    tokens = [service.login_local("alice.admin", PASSWORD)[1] for service in services]
    snapshots = [service.local_settings.accounts for service in services]
    for service, token in zip(services, tokens, strict=True):
        assert service.resolve(token, read_only=True).is_administrator
    before = writer.path.stat()
    previous_revision = snapshots[0]["alice.admin"].session_revision

    if independent_process:
        context = multiprocessing.get_context("spawn")
        worker = context.Process(target=_change_accounts, args=(str(writer.path), operation))
        worker.start()
        worker.join(timeout=20)
        assert worker.exitcode == 0
    else:
        _change_accounts(writer.path, operation)

    after = writer.path.stat()
    assert after.st_size == before.st_size
    # No timestamp/inode-change assumption: authority must refresh on the
    # filesystem actually hosting this test, even after rapid replacements.
    for service, token, previous in zip(services, tokens, snapshots, strict=True):
        # Read-only resolution cannot persist revocation and make another
        # reader's stale cache appear safe. Each reader must reject independently.
        assert service.resolve(token, read_only=True) is None
        current = service.local_settings.accounts
        assert current is not previous
        assert current["alice.admin"].session_revision != previous_revision
        assert current["alice.admin"].enabled
        assert "administrator" in current["alice.admin"].roles

    restarted = identity(tmp_path, writer)
    for token in tokens:
        assert restarted.resolve(token, read_only=True) is None
    password = "synthetic-updated-password" if operation == "password" else PASSWORD
    if operation == "password":
        for service in [*services, restarted]:
            with pytest.raises(LocalAuthenticationError, match="incorrect"):
                service.login_local("alice.admin", PASSWORD)
    for service in [*services, restarted]:
        _, fresh = service.login_local("alice.admin", password)
        assert service.resolve(fresh, read_only=True).is_administrator
    for service, token in zip(services, tokens, strict=True):
        assert service.resolve(token) is None
        assert restarted.resolve(token) is None
