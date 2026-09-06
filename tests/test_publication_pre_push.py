"""Exercise the real hook against isolated repositories; never contact a remote."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def command(root, *args, **kwargs):
    return subprocess.run(args, cwd=root, capture_output=True, text=True, **kwargs)


def repository(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    for args in [("init", "-q"), ("config", "user.name", "Synthetic Author"),
                 ("config", "user.email", "author@example.test")]:
        assert command(root, "git", *args).returncode == 0
    (root / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/publication-check.py", root / "scripts/publication-check.py")
    (root / "README.md").write_text("Synthetic example\n")
    commit(root)
    return root


def commit(root):
    assert command(root, "git", "add", ".").returncode == 0
    assert command(root, "git", "commit", "-qm", "Synthetic change").returncode == 0
    return command(root, "git", "rev-parse", "HEAD").stdout.strip()


def inspect(root, oid=None, ref="refs/heads/main"):
    oid = oid or command(root, "git", "rev-parse", "HEAD").stdout.strip()
    return command(root, "python3", str(ROOT / "scripts/pre-push-publication.py"),
                   input=f"refs/heads/main {oid} {ref} {'0' * 40}\n")


def test_clean_outgoing_history_passes(tmp_path):
    assert inspect(repository(tmp_path)).returncode == 0


def test_removed_private_residue_still_blocks_history(tmp_path):
    root = repository(tmp_path)
    (root / "private.txt").write_text("host." + "internal")
    commit(root)
    (root / "private.txt").unlink()
    commit(root)
    result = inspect(root)
    assert result.returncode != 0
    assert "host." not in result.stderr


def test_all_outgoing_refs_are_checked(tmp_path):
    root = repository(tmp_path)
    clean = command(root, "git", "rev-parse", "HEAD").stdout.strip()
    (root / "private.txt").write_text("host." + "internal")
    unsafe = commit(root)
    result = command(root, "python3", str(ROOT / "scripts/pre-push-publication.py"),
        input=f"main {clean} refs/heads/main {'0'*40}\nother {unsafe} refs/heads/other {'0'*40}\n")
    assert result.returncode != 0


def test_required_private_deny_file_fails_closed(tmp_path):
    root = repository(tmp_path)
    command(root, "git", "config", "recordbench.requirePrivatePublicationCheck", "true")
    assert inspect(root).returncode != 0
    deny = tmp_path / "deny.txt"
    deny.write_text("synthetic-disallowed-marker\n")
    deny.chmod(0o600)
    command(root, "git", "config", "recordbench.publicationDenyFile", str(deny))
    assert inspect(root).returncode == 0
    (root / "private.txt").write_text("synthetic-disallowed-marker")
    commit(root)
    assert inspect(root).returncode != 0


def test_tag_metadata_is_checked(tmp_path):
    root = repository(tmp_path)
    command(root, "git", "tag", "-a", "v-test", "-m", "host." + "internal")
    oid = command(root, "git", "rev-parse", "v-test").stdout.strip()
    assert inspect(root, oid, "refs/tags/v-test").returncode != 0


def test_unrelated_local_history_is_not_exported(tmp_path):
    root = repository(tmp_path)
    clean = command(root, "git", "rev-parse", "HEAD").stdout.strip()
    command(root, "git", "checkout", "-qb", "private-local")
    (root / "private.txt").write_text("host." + "internal")
    commit(root)
    assert inspect(root, clean).returncode == 0


def test_nested_tag_metadata_is_checked_even_without_inner_ref(tmp_path):
    root = repository(tmp_path)
    command(root, "git", "tag", "-a", "inner", "-m", "host." + "internal")
    command(root, "git", "tag", "-a", "outer", "inner", "-m", "Synthetic release")
    command(root, "git", "tag", "-d", "inner")
    oid = command(root, "git", "rev-parse", "outer").stdout.strip()
    assert inspect(root, oid, "refs/tags/outer").returncode != 0
