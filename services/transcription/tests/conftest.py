"""Synthetic tokenizer resources for tests that exercise real-backend admission."""
import pytest


@pytest.fixture
def punkt_inventory(tmp_path, monkeypatch):
    root = tmp_path / "nltk_data"
    for language in ("english", "spanish"):
        directory = root / "tokenizers" / "punkt_tab" / language
        directory.mkdir(parents=True)
        for name in ("collocations.tab", "sent_starters.txt", "abbrev_types.txt", "ortho_context.tab"):
            (directory / name).write_text("")
    monkeypatch.setenv("NLTK_DATA", str(root))
    return root
