"""CI candidate isolation retains the real outgoing-history publication guard."""

from pathlib import Path
import subprocess
import sys

from tests.test_publication_pre_push import command, commit, repository

ROOT = Path(__file__).resolve().parents[1]


def inspect(root, *, head=None, ref="refs/pull/123/merge"):
    head = head or command(root, "git", "rev-parse", "HEAD").stdout.strip()
    return subprocess.run([sys.executable, str(ROOT / "scripts/check-publication-candidate.py"),
        "--expected-head", head, "--publication-ref", ref], cwd=root,
        capture_output=True, text=True)


def test_unrelated_fetched_branch_does_not_block_clean_candidate(tmp_path):
    root = repository(tmp_path)
    clean = command(root, "git", "rev-parse", "HEAD").stdout.strip()
    command(root, "git", "checkout", "-qb", "unrelated")
    (root / "synthetic-residue.txt").write_text("fixture." + "internal")
    commit(root)
    command(root, "git", "checkout", "--detach", clean)
    assert inspect(root).returncode == 0


def test_removed_residue_in_candidate_ancestry_still_blocks(tmp_path):
    root = repository(tmp_path)
    (root / "synthetic-residue.txt").write_text("fixture." + "internal")
    commit(root)
    (root / "synthetic-residue.txt").unlink()
    commit(root)
    result = inspect(root)
    assert result.returncode != 0
    assert "fixture." not in result.stderr + result.stdout


def test_unexpected_head_modified_checkout_and_invalid_ref_fail_closed(tmp_path):
    root = repository(tmp_path)
    assert inspect(root, head="f" * 40).returncode != 0
    assert inspect(root, ref="--all").returncode != 0
    (root / "README.md").write_text("Uncommitted candidate change")
    assert inspect(root).returncode != 0


def test_annotated_tag_metadata_is_not_lost_by_peeling_to_head(tmp_path):
    root = repository(tmp_path)
    command(root, "git", "tag", "-a", "v-synthetic", "-m", "fixture." + "internal")
    assert inspect(root, ref="refs/tags/v-synthetic").returncode != 0


def test_clean_tag_and_wrong_target_tag_are_distinguished(tmp_path):
    root = repository(tmp_path)
    command(root, "git", "tag", "-a", "v-synthetic", "-m", "Synthetic release")
    assert inspect(root, ref="refs/tags/v-synthetic").returncode == 0
    (root / "README.md").write_text("Another synthetic candidate")
    commit(root)
    assert inspect(root, ref="refs/tags/v-synthetic").returncode != 0
