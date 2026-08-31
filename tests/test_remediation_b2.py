from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import case_intelligence.fixture_builder as fixture_builder
from case_intelligence.contracts import SourceVersion
from case_intelligence.fixture_builder import build_fixture
from tests.fixture_loader import ROOT, load_synthetic_fixture
from tests.support import source


@pytest.mark.parametrize(
    "reserved_path",
    [
        *[
            f"folder/{name}.txt"
            for name in (
                "CON",
                "PRN",
                "AUX",
                "NUL",
                "CLOCK$",
                *(f"COM{number}" for number in range(1, 10)),
                *(f"LPT{number}" for number in range(1, 10)),
            )
        ],
        "COM1.anything",
        "nested/deeper/pRn.TxT",
        "images/AuX... ",
        "folder/CON ",
        "NUL...",
        "LPT9 .alternate",
    ],
)
def test_relative_paths_reject_windows_device_aliases_in_every_component(
    reserved_path: str,
) -> None:
    data = source().model_dump()
    data["relative_path"] = reserved_path

    with pytest.raises(ValidationError, match="device component"):
        SourceVersion.model_validate(data)


@pytest.mark.parametrize(
    "valid_path",
    [
        "folder/CONSOLE.txt",
        "NULLED.log",
        "COM0.anything",
        "COM10.anything",
        "LPT0.txt",
        "LPT10.txt",
        "CLOCK.txt",
        "report.CON.txt",
        "photos/été 2026/scene one.svg",
    ],
)
def test_relative_paths_preserve_windows_device_near_misses(valid_path: str) -> None:
    data = source().model_dump()
    data["relative_path"] = valid_path

    assert SourceVersion.model_validate(data).relative_path == valid_path


@pytest.mark.parametrize(
    "colon_path",
    [
        "CON:stream",
        "NUL::$DATA",
        "COM1:foo",
        "folder/report.txt:stream",
        "nested/cOn:StReAm/file.txt",
        "ordinary:component/file.txt",
    ],
)
def test_relative_paths_reject_colons_in_any_component(colon_path: str) -> None:
    data = source().model_dump()
    data["relative_path"] = colon_path

    with pytest.raises(ValidationError, match="colon"):
        SourceVersion.model_validate(data)


def _records(manifest: dict) -> list[dict]:
    return [
        record
        for matter in manifest["matters"]
        for item in matter["sources"]
        for record in (item, item["representation"])
    ]


def _minimal_manifest(path: str) -> dict:
    return {
        "fixture_id": "synthetic-security-test",
        "provenance": "synthetic",
        "confidential_data": False,
        "requires_model": False,
        "requires_network": False,
        "matters": [
            {
                "matter_id": "matter-test",
                "sources": [
                    {
                        "path": path,
                        "representation": {"path": "representation.txt"},
                    }
                ],
            }
        ],
    }


def test_builder_constructs_committed_fixture_in_caller_owned_tmp_path(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "constructed"
    destination.mkdir()

    result = build_fixture(ROOT, destination)
    committed = load_synthetic_fixture(verify_files=True)

    assert result.manifest == committed
    assert result.file_count == 12
    assert result.root == destination.resolve()
    assert (destination / "manifest.json").read_bytes() == (
        ROOT / "manifest.json"
    ).read_bytes()
    for record in _records(committed):
        assert (destination / record["path"]).read_bytes() == (
            ROOT / record["path"]
        ).read_bytes()


@pytest.mark.parametrize(
    "malicious_path",
    [
        "/absolute.txt",
        "../escape.txt",
        "folder/../../escape.txt",
        "folder/../normalized.txt",
        r"C:\device.txt",
        r"\\host\share\file.txt",
        "folder/report.txt:stream",
        "NUL::$DATA",
    ],
)
def test_builder_rejects_absolute_traversal_and_normalizing_manifest_paths_before_copy(
    tmp_path: Path,
    malicious_path: str,
) -> None:
    manifest = copy.deepcopy(load_synthetic_fixture())
    manifest["matters"][0]["sources"][0]["path"] = malicious_path
    destination = tmp_path / "destination"
    destination.mkdir()

    with pytest.raises(ValueError):
        build_fixture(ROOT, destination, manifest=manifest)

    assert list(destination.iterdir()) == []


@pytest.mark.parametrize(
    ("first_path", "second_path"),
    [
        ("matter-alpha/report.txt", "matter-alpha/report.txt"),
        ("matter-alpha/report.txt", "MATTER-ALPHA/REPORT.TXT"),
        ("matter-alpha/report.txt", "matter-alpha/report.txt."),
        ("matter-alpha/report.txt", "matter-alpha/report.txt "),
    ],
)
def test_builder_rejects_duplicate_or_windows_ambiguous_destinations_before_copy(
    tmp_path: Path,
    first_path: str,
    second_path: str,
) -> None:
    manifest = copy.deepcopy(load_synthetic_fixture())
    records = _records(manifest)
    records[0]["path"] = first_path
    records[1]["path"] = second_path
    destination = tmp_path / "destination"
    destination.mkdir()

    with pytest.raises(ValueError, match="duplicate or ambiguous"):
        build_fixture(ROOT, destination, manifest=manifest)

    assert list(destination.iterdir()) == []


def test_builder_rejects_source_symlink_before_copy(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside")
    (source_root / "payload.txt").symlink_to(outside)
    (source_root / "representation.txt").write_bytes(b"representation")
    destination = tmp_path / "destination"
    destination.mkdir()

    with pytest.raises(ValueError, match="symlink"):
        build_fixture(
            source_root,
            destination,
            manifest=_minimal_manifest("payload.txt"),
        )

    assert list(destination.iterdir()) == []


def test_builder_rejects_non_regular_source_before_copy(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "payload").mkdir()
    (source_root / "representation.txt").write_bytes(b"representation")
    destination = tmp_path / "destination"
    destination.mkdir()

    with pytest.raises(ValueError, match="regular file"):
        build_fixture(
            source_root,
            destination,
            manifest=_minimal_manifest("payload"),
        )

    assert list(destination.iterdir()) == []


def test_builder_rejects_symlink_in_destination_ancestry(tmp_path: Path) -> None:
    real_destination = tmp_path / "real-destination"
    real_destination.mkdir()
    linked_destination = tmp_path / "linked-destination"
    linked_destination.symlink_to(real_destination, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        build_fixture(ROOT, linked_destination)

    assert list(real_destination.iterdir()) == []


def test_builder_rejects_nonempty_destination_without_modifying_it(tmp_path: Path) -> None:
    destination = tmp_path / "destination"
    destination.mkdir()
    sentinel = destination / "caller-owned.txt"
    sentinel.write_text("preserve me", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        build_fixture(ROOT, destination)

    assert sentinel.read_text(encoding="utf-8") == "preserve me"


def test_builder_rejects_symlinked_manifest_file(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    external_manifest = tmp_path / "external-manifest.json"
    external_manifest.write_text(json.dumps(_minimal_manifest("payload.txt")))
    (source_root / "manifest.json").symlink_to(external_manifest)
    destination = tmp_path / "destination"
    destination.mkdir()

    with pytest.raises(ValueError, match="symlink"):
        build_fixture(source_root, destination)

    assert list(destination.iterdir()) == []


def test_builder_fails_closed_without_linux_openat2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "payload.txt").write_bytes(b"inside")
    (source_root / "representation.txt").write_bytes(b"representation")
    destination = tmp_path / "destination"
    destination.mkdir()
    monkeypatch.setattr(fixture_builder.sys, "platform", "not-linux")

    with pytest.raises(RuntimeError, match="requires Linux openat2"):
        build_fixture(
            source_root,
            destination,
            manifest=_minimal_manifest("payload.txt"),
        )

    assert list(destination.iterdir()) == []


def test_builder_parent_moved_outside_cannot_redirect_destination_write(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    (source_root / "sub").mkdir(parents=True)
    (source_root / "sub" / "payload.txt").write_bytes(b"inside")
    (source_root / "representation.txt").write_bytes(b"representation")
    destination = tmp_path / "destination"
    destination.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    moved_parent = outside / "moved-destination-sub"
    swapped = False

    def swap_parent(phase: str, relative_path: str) -> None:
        nonlocal swapped
        if phase == "destination_parent" and relative_path == "sub/payload.txt":
            (destination / "sub").rename(moved_parent)
            (destination / "sub").symlink_to(moved_parent, target_is_directory=True)
            swapped = True

    with pytest.raises(ValueError, match="beneath its root"):
        build_fixture(
            source_root,
            destination,
            manifest=_minimal_manifest("sub/payload.txt"),
            _test_hook=swap_parent,
        )

    assert swapped
    assert moved_parent.parent == outside
    assert (destination / "sub").is_symlink()
    assert not (moved_parent / "payload.txt").exists()


def test_builder_parent_moved_outside_cannot_redirect_source_read(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    (source_root / "sub").mkdir(parents=True)
    (source_root / "sub" / "payload.txt").write_bytes(b"inside")
    (source_root / "representation.txt").write_bytes(b"representation")
    outside = tmp_path / "outside"
    outside.mkdir()
    moved_parent = outside / "moved-source-sub"
    destination = tmp_path / "destination"
    destination.mkdir()
    swapped = False

    def swap_parent(phase: str, relative_path: str) -> None:
        nonlocal swapped
        if phase == "source_parent" and relative_path == "sub/payload.txt":
            (source_root / "sub").rename(moved_parent)
            (moved_parent / "payload.txt").write_bytes(b"outside-after-move")
            (source_root / "sub").symlink_to(moved_parent, target_is_directory=True)
            swapped = True

    with pytest.raises(ValueError, match="beneath its root"):
        build_fixture(
            source_root,
            destination,
            manifest=_minimal_manifest("sub/payload.txt"),
            _test_hook=swap_parent,
        )

    assert swapped
    assert moved_parent.parent == outside
    assert (moved_parent / "payload.txt").read_bytes() == b"outside-after-move"
    assert list(destination.iterdir()) == []
