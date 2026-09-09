from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import recordbench_install as installer  # noqa: E402


def test_installer_dry_run_has_real_phases_and_writes_nothing(tmp_path, ready_host, monkeypatch, capsys) -> None:
    node = tmp_path.resolve() / "node"
    monkeypatch.setattr(sys, "argv", [
            str(ROOT / "install"),
            "install",
            "--root",
            str(node),
            "--auth",
            "local",
            "--models",
            "none",
            "--non-interactive",
            "--prepare-only",
            "--dry-run",
            "--no-color",
        ])
    assert installer.main() == 0
    output = capsys.readouterr().out
    for marker in (
        "HOST HANDSHAKE",
        "CLAIM NODE STORAGE",
        "LOAD RELEASE CAPSULE",
        "IDENTITY + FRONT DOOR",
        "FORGE RUNTIME",
        "SEAL CONTROL PLANE",
        "NODE ARMED",
        "ACCESS GRANTED",
    ):
        assert marker in output
    assert not node.exists()
    assert "password=" not in output.casefold()
    assert "token=" not in output.casefold()


def test_capability_profiles_have_conservative_gpu_contracts() -> None:
    assert installer._required_gpu_count("none") == 0
    assert installer._required_gpu_count("review") == 1
    assert installer._required_gpu_count("transcription") == 1
    assert installer._required_gpu_count("all") == 1
    one = (installer.GpuDevice("0", "Synthetic GPU", 24_576, 24_000),)
    shared = installer._gpu_plan("all", one)
    assert shared.layout == "shared"
    assert shared.generator_gpus == ("0",)
    assert shared.transcription_gpu == "0"
    assert shared.retrieval_device == "cpu"

    many = tuple(
        installer.GpuDevice(str(index), f"Synthetic GPU {index}", 48_000, 40_000)
        for index in range(8)
    )
    split = installer._gpu_plan("all", many)
    assert split.layout == "split"
    assert split.generator_gpus == ("0",)
    assert split.transcription_gpu == "1"
    assert split.retrieval_device == "cuda"
    assert split.retrieval_gpu == "2"


def test_automatic_full_profile_resolves_on_one_or_eight_gpus() -> None:
    args = installer._parser().parse_args(["install", "--models", "all"])
    one = (
        installer.GpuDevice(
            "0", "Synthetic 24 GiB GPU", 24_576, 24_000, 8.0
        ),
    )
    one_gpu, one_model = installer._resolve_gpu_plans(args, "all", one)
    assert one_gpu.layout == "shared"
    assert one_gpu.generator_gpus == ("0",)
    assert one_gpu.transcription_gpu == "0"
    assert one_gpu.retrieval_device == "cpu"
    assert one_model.profile == "portable"

    eight = tuple(
        installer.GpuDevice(
            str(index), f"Synthetic GPU {index}", 48_000, 46_000, 8.9
        )
        for index in range(8)
    )
    eight_gpu, eight_model = installer._resolve_gpu_plans(args, "all", eight)
    assert eight_gpu.layout == "split"
    assert eight_gpu.generator_gpus == ("0",)
    assert eight_gpu.transcription_gpu == "1"
    assert eight_gpu.retrieval_gpu == "2"
    assert eight_model.profile == "quality"


def test_gpu_inventory_parses_capability_and_auto_ranks_mixed_cards() -> None:
    devices = installer._parse_gpu_inventory(
        "0, Synthetic Small, 16384, 15000, 7.5\n"
        "1, Synthetic Large Busy, 49152, 12000, 8.9\n"
        "2, Synthetic Large Free, 49152, 47000, 8.9\n"
    )
    plan = installer._gpu_plan("all", devices)
    assert plan.generator_gpus == ("2",)
    assert plan.transcription_gpu == "0"
    assert plan.retrieval_device == "cuda"
    assert plan.retrieval_gpu == "1"


def test_gpu_planner_ignores_incompatible_cards_and_rejects_explicit_use() -> None:
    devices = (
        installer.GpuDevice("0", "Synthetic Legacy", 48_000, 48_000, 7.0),
        installer.GpuDevice("1", "Synthetic Supported", 24_576, 24_000, 8.0),
    )
    plan = installer._gpu_plan("all", devices)
    assert plan.generator_gpus == ("1",)
    assert plan.transcription_gpu == "1"
    with pytest.raises(RuntimeError, match="not visible"):
        installer._gpu_plan("review", devices, generator_gpus="0")


def test_gpu_topology_supports_explicit_multi_gpu_overrides() -> None:
    devices = tuple(
        installer.GpuDevice(str(index), f"Synthetic GPU {index}", 48_000, 40_000)
        for index in range(8)
    )
    plan = installer._gpu_plan(
        "all",
        devices,
        generator_gpus="3,4,5,6",
        transcription_gpu="7",
        retrieval_device="cuda",
        retrieval_gpu="2",
    )
    assert plan.environment()["RECORDBENCH_GENERATOR_TENSOR_PARALLEL"] == "4"
    assert plan.generator_gpus == ("3", "4", "5", "6")
    assert plan.transcription_gpu == "7"
    assert plan.retrieval_gpu == "2"


def test_review_model_tier_adapts_to_gpu_memory_and_sharing() -> None:
    portable_device = (
        installer.GpuDevice("0", "Synthetic 24 GiB GPU", 24_576, 24_000),
    )
    shared = installer._gpu_plan("all", portable_device)
    portable = installer._review_model_plan(
        "all", portable_device, shared, requested_profile="auto"
    )
    assert portable.profile == "portable"
    assert portable.model_id == "Qwen/Qwen3.5-4B"
    assert portable.dtype == "half"
    assert portable.gpu_utilization == 0.50
    assert portable.max_sequences == 4
    assert portable.generation_concurrency == 2
    assert portable.transcription_min_free_vram_mib == 7_000

    quality_devices = (
        installer.GpuDevice("0", "Synthetic GPU 0", 48_000, 46_000),
        installer.GpuDevice("1", "Synthetic GPU 1", 48_000, 46_000),
    )
    split = installer._gpu_plan("all", quality_devices)
    quality = installer._review_model_plan(
        "all", quality_devices, split, requested_profile="auto"
    )
    assert quality.profile == "quality"
    assert quality.model_id == "Qwen/Qwen3.5-9B"
    assert quality.dtype == "half"
    assert quality.gpu_utilization == 0.72
    assert quality.max_sequences == 8
    assert quality.generation_concurrency == 4


def test_automatic_plan_downgrades_model_before_rejecting_usable_hardware() -> None:
    devices = (
        installer.GpuDevice("0", "Synthetic 48 GiB", 48_000, 30_000, 8.9),
        installer.GpuDevice("1", "Synthetic 24 GiB", 24_576, 20_000, 8.9),
    )
    args = installer._parser().parse_args(["install", "--models", "all"])
    gpu_plan, model_plan = installer._resolve_gpu_plans(args, "all", devices)
    assert gpu_plan.layout == "split"
    assert model_plan.profile == "portable"
    assert model_plan.gpu_utilization == 0.60
    assert model_plan.max_sequences == 4


def test_explicit_gpu_plan_is_never_silently_rewritten() -> None:
    devices = (
        installer.GpuDevice("0", "Synthetic Busy", 48_000, 20_000, 8.9),
        installer.GpuDevice("1", "Synthetic Free", 24_576, 24_000, 8.9),
    )
    args = installer._parser().parse_args(
        [
            "install",
            "--models",
            "all",
            "--gpu-layout",
            "split",
            "--generator-gpus",
            "0",
            "--transcription-gpu",
            "1",
            "--review-model-profile",
            "quality",
        ]
    )
    with pytest.raises(RuntimeError, match="currently has|needs at least"):
        installer._resolve_gpu_plans(args, "all", devices)


def test_review_model_tier_rejects_an_unworkable_explicit_shape() -> None:
    small = (installer.GpuDevice("0", "Synthetic GPU", 12_000, 12_000),)
    shared = installer._gpu_plan("all", small)
    with pytest.raises(RuntimeError, match="needs at least"):
        installer._review_model_plan(
            "all", small, shared, requested_profile="portable"
        )


def test_review_model_plan_rejects_current_gpu_contention() -> None:
    busy = (
        installer.GpuDevice(
            "0", "Synthetic Busy GPU", 24_576, 8_000, 8.0
        ),
    )
    shared = installer._gpu_plan("all", busy)
    with pytest.raises(RuntimeError, match="currently has"):
        installer._review_model_plan("all", busy, shared)


def test_model_catalog_has_one_pinned_generator_per_review_tier() -> None:
    catalog = json.loads((ROOT / "config" / "models.json").read_text())
    generators = {
        item["profile"]: item
        for item in catalog["models"]
        if item["group"] == "review" and item["role"] == "generator"
    }
    assert set(generators) == {"portable", "quality"}
    for item in generators.values():
        assert len(item["revision"]) == 40
        assert item["gated"] is False


def test_transcription_model_modules_are_independently_selected() -> None:
    assert installer._model_stage_groups(
        "transcription",
        transcription_languages=("en",),
        diarization=False,
    ) == ("transcription-asr", "transcription-alignment-en")
    assert installer._model_stage_groups(
        "all",
        transcription_languages=("en", "es"),
        diarization=True,
    ) == (
        "review",
        "transcription-asr",
        "transcription-alignment-en",
        "transcription-alignment-es",
        "transcription-diarization",
    )
    with pytest.raises(RuntimeError, match="requires a transcription"):
        installer._model_stage_groups(
            "review", transcription_languages=("en",), diarization=True
        )


def test_selected_profile_cannot_accept_missing_ai_capabilities() -> None:
    healthy = {
        "capabilities": {
            "answering": "ready",
            "search": "word + meaning",
            "transcription": "local WhisperX v2",
        }
    }
    assert installer._selected_capabilities_ready(healthy, "none")
    assert installer._selected_capabilities_ready(healthy, "review")
    assert installer._selected_capabilities_ready(healthy, "transcription")
    assert installer._selected_capabilities_ready(healthy, "all")

    missing = {
        "capabilities": {
            "answering": "temporarily unavailable",
            "search": "word search only",
            "transcription": "temporarily unavailable",
        }
    }
    assert installer._selected_capabilities_ready(missing, "none")
    assert not installer._selected_capabilities_ready(missing, "review")
    assert not installer._selected_capabilities_ready(missing, "transcription")
    assert not installer._selected_capabilities_ready(missing, "all")


def test_plain_noninteractive_install_defaults_to_cpu_evaluation(tmp_path, ready_host, monkeypatch, capsys) -> None:
    node = tmp_path.resolve() / "node"
    monkeypatch.setattr(sys, "argv", [
            str(ROOT / "install"),
            "install",
            "--root",
            str(node),
            "--auth",
            "local",
            "--non-interactive",
            "--prepare-only",
            "--dry-run",
            "--no-color",
        ])
    assert installer.main() == 0
    output = capsys.readouterr().out
    assert "model payload   :: none" in output
    assert "nvidia-smi" not in output
    assert not node.exists()


def test_federated_identity_inputs_are_declarative_without_cli_secrets() -> None:
    options = {action.dest for action in installer._parser()._actions}
    assert {
        "oidc_issuer",
        "oidc_client_id",
        "oidc_client_secret_file",
        "oidc_allowed_groups",
        "oidc_admin_groups",
        "kerberos_realm",
        "kerberos_allowed_groups",
        "kerberos_admin_groups",
        "kerberos_keytab",
    } <= options
    assert "oidc_client_secret" not in options


def test_release_capsule_is_content_addressed_and_allowlisted(tmp_path) -> None:
    root = tmp_path / "node"
    root.mkdir(mode=0o700)
    console = installer.Console(color=False, quiet=True)
    release_id, release = installer._stage_release(console, root, dry_run=False)
    manifest = json.loads((release / "RELEASE_MANIFEST.json").read_text())
    assert manifest["release_id"] == release_id
    assert len(manifest["source_sha256"]) == 64
    assert (release / "compose.yaml").is_file()
    assert (release / "services/transcription/src").is_dir()
    assert not (release / ".git").exists()
    assert not (release / ".venv").exists()
    assert not (release / "tests").exists()


def test_generated_environment_is_quoted_and_rejects_line_injection() -> None:
    text = installer._env_text(
        {"RECORDBENCH_PATH": "/srv/Record Bench", "RECORDBENCH_VALUE": 7},
        "synthetic",
    )
    assert 'RECORDBENCH_PATH="/srv/Record Bench"' in text
    assert 'RECORDBENCH_VALUE="7"' in text
    with pytest.raises(RuntimeError, match="environment value"):
        installer._env_text({"RECORDBENCH_PATH": "safe\nINJECT=1"}, "synthetic")


def test_generated_environment_round_trips_through_health_parser(tmp_path) -> None:
    path = tmp_path / "compose.env"
    path.write_text(
        installer._env_text(
            {
                "RECORDBENCH_HTTPS_PORT": 18443,
                "RECORDBENCH_SERVER_NAME": "recordbench.example.test",
                "RECORDBENCH_PATH": "/srv/Record Bench",
            },
            "synthetic",
        ),
        encoding="utf-8",
    )
    values = installer._dotenv(path)
    assert int(values["RECORDBENCH_HTTPS_PORT"]) == 18443
    assert values["RECORDBENCH_SERVER_NAME"] == "recordbench.example.test"
    assert values["RECORDBENCH_PATH"] == "/srv/Record Bench"


def test_existing_secret_must_remain_owner_only(tmp_path) -> None:
    secret = tmp_path / "secret"
    secret.write_text("synthetic-secret-value-with-length\n", encoding="utf-8")
    secret.chmod(0o644)
    with pytest.raises(RuntimeError, match="unsafe"):
        installer._secret(secret)
    secret.chmod(0o600)
    assert installer._secret(secret) == "synthetic-secret-value-with-length"


def test_update_uses_versioned_images_backup_and_rollback_contracts() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    source = (ROOT / "scripts/recordbench_install.py").read_text(encoding="utf-8")
    assert "RECORDBENCH_RELEASE_ID" in compose
    assert "SNAPSHOT BEFORE MUTATION" in source
    assert "--no-backup" in source
    assert "Prior release restored and healthy" in source
    assert "docker image prune" not in source
    assert "git pull" not in source


def test_compose_validation_uses_an_isolated_temporary_node() -> None:
    source = (ROOT / "scripts/compose-check.sh").read_text(encoding="utf-8")
    assert "mktemp -d" in source
    assert "trap cleanup EXIT" in source
    assert "config --quiet" in source
    assert "compose.kerberos.yaml" in source


def test_application_health_accepts_a_useful_node_without_optional_models() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "p['status'] in {'ok','degraded'}" in dockerfile
    assert "p['storage']['status']=='ready'" in dockerfile


def test_clamav_retains_only_capabilities_needed_by_upstream_entrypoint() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    clamav = compose.split("\n  clamav:\n", 1)[1].split("\n  retrieval:\n", 1)[0]
    assert "cap_drop: [ALL]" in clamav
    assert "cap_add: [CHOWN, DAC_OVERRIDE, FOWNER, SETGID, SETUID]" in clamav
    assert "read_only: true" not in clamav
    assert "clamav-signatures:/var/lib/clamav" in clamav
    assert 'CLAMAV_NO_FRESHCLAMD: "true"' in clamav
    assert "clamav-updater: {condition: service_healthy}" in clamav
    assert "networks: [services]" in clamav
    updater = clamav.split("\n  clamav-updater:\n", 1)[1]
    assert "networks: [updates]" in updater
    assert 'command: ["freshclam", "--daemon", "--foreground"' in updater
    assert "-mmin -4320" in updater


def test_read_only_gateway_has_a_narrow_runtime_configuration_tmpfs() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    gateway = compose.split("\n  gateway:\n", 1)[1].split("\n  model-stager:\n", 1)[0]
    assert "read_only: true" in gateway
    assert "cap_add: [CHOWN, DAC_OVERRIDE, NET_BIND_SERVICE, SETGID, SETUID]" in gateway
    assert "/etc/nginx/conf.d:rw,noexec,nosuid,nodev,size=1m" in gateway
    assert "./deploy/gateway/default.conf.template:/etc/nginx/templates/default.conf.template:ro" in gateway


def test_provisioning_seal_is_release_specific_and_owner_only(tmp_path) -> None:
    root = tmp_path / "node"
    (root / "state").mkdir(parents=True)
    installation = {
        "release_id": "0.1.0-alpha.1-synthetic",
        "auth": "local",
        "models": "none",
    }
    assert not installer._provisioning_complete(root, installation)
    installer._seal_provisioning(root, installation)
    marker = root / "state" / "provisioned.json"
    assert marker.stat().st_mode & 0o777 == 0o600
    assert installer._provisioning_complete(root, installation)
    assert not installer._provisioning_complete(
        root, {**installation, "release_id": "0.1.0-alpha.1-new"}
    )


def test_partial_local_resume_requires_explicit_bootstrap_identity(tmp_path, monkeypatch) -> None:
    root = tmp_path / "node"
    (root / "secrets").mkdir(parents=True)
    (root / "state").mkdir()
    (root / "matter-storage").mkdir()
    (root / "installation.json").write_text(
        json.dumps(
            {
                "release_id": "synthetic",
                "release_path": str(ROOT),
                "storage_root": str(root / "matter-storage"),
                "auth": "local",
                "models": "none",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(installer, "_run", lambda *args, **kwargs: subprocess.CompletedProcess([], 0))
    args = installer._parser().parse_args(
        ["install", "--root", str(root), "--resume", "--non-interactive"]
    )
    with pytest.raises(RuntimeError, match="unfinished local installation"):
        installer._provision(
            installer.Console(color=False, quiet=True),
            args,
            root,
            "local",
            "none",
            None,
            None,
        )


@pytest.fixture
def ready_host(monkeypatch, tmp_path):
    actual_uid = os.geteuid()
    original_stat = Path.stat
    def synthetic_owner(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if result.st_uid == actual_uid and (actual_uid != 0 or path == tmp_path or tmp_path in path.parents):
            fields = list(result)
            fields[4] = 1000
            return os.stat_result(fields)
        return result
    monkeypatch.setattr(Path, "stat", synthetic_owner)
    import pwd
    from types import SimpleNamespace
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir="/home/synthetic-service"))
    monkeypatch.setattr(installer.platform, "system", lambda: "Linux")
    monkeypatch.setattr(installer.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(installer.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(installer.os, "getegid", lambda: 1000)
    monkeypatch.setattr(installer.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(installer.shutil, "disk_usage", lambda path: type("Disk", (), {"free": 400 * 1024**3})())
    monkeypatch.setattr(installer, "_probe", lambda command: subprocess.CompletedProcess(command, 0, '{"nvidia": {}}' if "{{json .Runtimes}}" in command else "1.0", ""))


def preflight_args(tmp_path, *extra):
    return installer._parser().parse_args(["preflight", "--root", str(tmp_path.resolve() / "new node with spaces"), *extra])


def checks_by_name(result):
    return {check.name: check for check in result.checks}


def test_preflight_cpu_has_optional_gpu_and_never_writes(tmp_path, ready_host, monkeypatch):
    args = preflight_args(tmp_path)
    monkeypatch.setattr(installer.Path, "mkdir", lambda *a, **kw: pytest.fail("preflight attempted a write"))
    result = installer._collect_preflight("none", args)
    assert result.ready
    assert checks_by_name(result)["gpu"].blocking is False
    assert not args.root.exists()
    assert result.payload()["schema_version"] == 1
    assert set(result.payload()["checks"][0]) == {"name", "state", "observed", "required_capability", "blocking", "remedy"}


@pytest.mark.parametrize("system,machine", [("Darwin", "arm64"), ("Linux", "aarch64"), ("Windows", "AMD64")])
def test_preflight_unsupported_host_stops_before_other_probes(tmp_path, ready_host, monkeypatch, system, machine):
    monkeypatch.setattr(installer.platform, "system", lambda: system)
    monkeypatch.setattr(installer.platform, "machine", lambda: machine)
    monkeypatch.setattr(installer, "_probe", lambda command: pytest.fail("unsupported host reached runtime"))
    result = installer._collect_preflight("none", preflight_args(tmp_path))
    assert not result.ready
    assert [check.name for check in result.checks] == ["host"]


@pytest.mark.parametrize("missing", ["docker", "openssl"])
def test_preflight_missing_tools_are_actionable(tmp_path, ready_host, monkeypatch, missing):
    monkeypatch.setattr(installer.shutil, "which", lambda name: None if name == missing else "/usr/bin/" + name)
    result = installer._collect_preflight("none", preflight_args(tmp_path))
    check = checks_by_name(result)[missing]
    assert not result.ready and check.blocking and check.remedy


@pytest.mark.parametrize("failed", ["docker-access", "compose"])
def test_preflight_runtime_failure_never_echoes_output(tmp_path, ready_host, monkeypatch, failed):
    def probe(command):
        failure = ("compose" in command) == (failed == "compose")
        return subprocess.CompletedProcess(command, int(failure), "synthetic-private-output", "synthetic-private-output")
    monkeypatch.setattr(installer, "_probe", probe)
    result = installer._collect_preflight("none", preflight_args(tmp_path))
    assert checks_by_name(result)[failed].state == "fail"
    assert "synthetic-private-output" not in json.dumps(result.payload())


@pytest.mark.parametrize("uid,gid", [(0, 1000), (1000, 0)])
def test_preflight_root_identity_blocks_even_dry_run(tmp_path, ready_host, monkeypatch, uid, gid):
    monkeypatch.setattr(installer.os, "geteuid", lambda: uid)
    monkeypatch.setattr(installer.os, "getegid", lambda: gid)
    args = preflight_args(tmp_path, "--dry-run")
    assert checks_by_name(installer._collect_preflight("none", args))["ownership"].state == "fail"


def test_preflight_capacity_and_write_access_are_separate(tmp_path, ready_host, monkeypatch):
    monkeypatch.setattr(installer.os, "access", lambda *a: False)
    monkeypatch.setattr(installer.shutil, "disk_usage", lambda path: type("Disk", (), {"free": 99 * 1024**3})())
    checks = checks_by_name(installer._collect_preflight("none", preflight_args(tmp_path)))
    assert checks["node-storage"].state == "fail"
    assert checks["node-storage-reserve"].state == "fail"
    assert checks["capacity-target"].blocking is False


def test_preflight_symlink_and_non_directory_storage_block(tmp_path, ready_host):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    args = preflight_args(tmp_path, "--storage-root", str(link / "new"))
    assert checks_by_name(installer._collect_preflight("none", args))["matter-storage"].state == "fail"
    target.rmdir()
    target.write_text("synthetic")
    args.storage_root = target
    assert checks_by_name(installer._collect_preflight("none", args))["matter-storage"].state == "fail"


@pytest.mark.parametrize("options", [["--bind-address", "0.0.0.0"], ["--tls-cert", "/missing/cert"], ["--tls-cert", "/missing/cert", "--tls-key", "/missing/key"]])
def test_preflight_tls_missing_prerequisites_block(tmp_path, ready_host, options):
    result = installer._collect_preflight("none", preflight_args(tmp_path, *options))
    assert checks_by_name(result)["tls"].state == "fail"


def test_preflight_selected_gpu_profile_checks_real_plan(tmp_path, ready_host, monkeypatch):
    def probe(command):
        output = '{"nvidia": {}}' if "{{json .Runtimes}}" in command else "0, Synthetic GPU, 24576, 24000, 8.0" if command[0] == "nvidia-smi" else "1.0"
        return subprocess.CompletedProcess(command, 0, output, "")
    monkeypatch.setattr(installer, "_probe", probe)
    args = preflight_args(tmp_path, "--models", "review")
    assert installer._collect_preflight("review", args).ready
    args.generator_gpus = "9"
    assert checks_by_name(installer._collect_preflight("review", args))["gpu"].state == "fail"
    monkeypatch.setattr(installer.shutil, "which", lambda name: None if name == "nvidia-smi" else name)
    assert not installer._collect_preflight("review", args).ready
    assert installer._collect_preflight("none", args).ready


def test_preflight_json_is_single_document_and_returns_failure(tmp_path, ready_host, monkeypatch, capsys):
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0)
    monkeypatch.setattr(sys, "argv", ["install", "preflight", "--root", str(tmp_path / "new"), "--json"])
    assert installer.main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ready"] is False
    assert not (tmp_path / "new").exists()


def test_install_blocking_preflight_does_not_create_state(tmp_path, ready_host, monkeypatch):
    monkeypatch.setattr(installer.shutil, "which", lambda name: None)
    node = tmp_path / "new"
    monkeypatch.setattr(sys, "argv", ["install", "--root", str(node), "--non-interactive"])
    assert installer.main() == 1
    assert not node.exists()


@pytest.mark.parametrize("output,returncode", [('{}', 0), ('[]', 0), ('not-json', 0), ('{"nvidia": {}}', 1)])
def test_preflight_gpu_runtime_requires_successful_registered_engine(tmp_path, ready_host, monkeypatch, output, returncode):
    def probe(command):
        if "{{json .Runtimes}}" in command:
            return subprocess.CompletedProcess(command, returncode, output, "")
        return subprocess.CompletedProcess(command, 0, "0, Synthetic GPU, 24576, 24000, 8.0", "")
    monkeypatch.setattr(installer, "_probe", probe)
    result = installer._collect_preflight("review", preflight_args(tmp_path))
    assert checks_by_name(result)["gpu"].state == "pass"
    assert checks_by_name(result)["gpu-runtime"].state == "fail"


def test_preflight_runtime_timeout_is_actionable(tmp_path, ready_host, monkeypatch):
    def probe(command):
        raise subprocess.TimeoutExpired(command, 20)
    monkeypatch.setattr(installer, "_probe", probe)
    result = installer._collect_preflight("review", preflight_args(tmp_path))
    assert not result.ready
    assert checks_by_name(result)["docker-access"].remedy
    assert checks_by_name(result)["gpu"].remedy


def test_preflight_existing_directory_requires_current_owner(tmp_path, ready_host, monkeypatch):
    args = preflight_args(tmp_path)
    args.root.mkdir()
    monkeypatch.setattr(installer.os, "geteuid", lambda: args.root.stat().st_uid + 1)
    assert checks_by_name(installer._collect_preflight("none", args))["node-storage"].state == "fail"


def test_preflight_supplied_lan_tls_pair_is_read_only(tmp_path, ready_host):
    cert, key = tmp_path / "synthetic.crt", tmp_path / "synthetic.key"
    cert.write_text("synthetic certificate placeholder")
    key.write_text("synthetic key placeholder")
    args = preflight_args(tmp_path, "--bind-address", "0.0.0.0", "--tls-cert", str(cert), "--tls-key", str(key))
    check = checks_by_name(installer._collect_preflight("none", args))["tls"]
    assert check.state == "pass"
    assert "trust must be verified" in check.observed
    assert not args.root.exists()


@pytest.mark.parametrize("options", [
    ["--models", "none", "--enable-diarization"],
    ["--models", "review", "--enable-diarization"],
    ["--models", "transcription", "--transcription-languages", "fr"],
    ["--models", "all", "--transcription-languages", ""],
])
def test_preflight_rejects_invalid_model_option_combinations(tmp_path, ready_host, options):
    args = preflight_args(tmp_path, *options)
    result = installer._collect_preflight(args.models, args)
    assert not result.ready
    assert checks_by_name(result)["model-options"].state == "fail"
    assert not args.root.exists()


def test_preflight_nonempty_root_requires_explicit_resume(tmp_path, ready_host, monkeypatch):
    args = preflight_args(tmp_path)
    args.root.mkdir()
    (args.root / "existing.txt").write_text("synthetic existing data")
    original_stat = installer.Path.stat
    def synthetic_owned(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path == args_root:
            fields = list(result)
            fields[4] = 1000
            return installer.os.stat_result(fields)
        return result
    args_root = args.root
    monkeypatch.setattr(installer.Path, "stat", synthetic_owned)
    blocked = installer._collect_preflight("none", args)
    assert not blocked.ready
    assert checks_by_name(blocked)["node-empty"].state == "fail"
    args.resume = True
    assert not installer._collect_preflight("none", args).ready
    (args.root / "installation.json").write_text(json.dumps({
        "release_path": str(ROOT), "auth": "local", "models": "none", "profiles": ["tools"],
    }))
    assert installer._collect_preflight("none", args).ready
    assert (args.root / "existing.txt").read_text() == "synthetic existing data"


def test_invalid_model_options_stop_install_before_state_creation(tmp_path, ready_host, monkeypatch):
    node = tmp_path.resolve() / "uncreated node"
    monkeypatch.setattr(sys, "argv", ["install", "--root", str(node), "--models", "none",
                                     "--enable-diarization", "--non-interactive"])
    assert installer.main() == 1
    assert not node.exists()


@pytest.mark.parametrize("options", [
    ["--generator-gpu-utilization", "1"],
    ["--retrieval-device", "cpu", "--retrieval-gpu", "0"],
])
def test_cpu_preflight_validates_gpu_options_without_gpu_probe(tmp_path, ready_host, monkeypatch, options):
    args = preflight_args(tmp_path, "--models", "none", *options)
    result = installer._collect_preflight("none", args)
    assert not result.ready
    assert checks_by_name(result)["gpu-options"].state == "fail"
    assert not args.root.exists()


@pytest.mark.parametrize("field", ["root", "storage_root"])
def test_preflight_rejects_home_directory_dot_dot_alias(tmp_path, ready_host, monkeypatch, field):
    synthetic_home = tmp_path.resolve() / "synthetic-home"
    synthetic_home.mkdir()
    monkeypatch.setattr(installer.Path, "home", classmethod(lambda cls: synthetic_home))
    args = preflight_args(tmp_path, "--resume")
    setattr(args, field, synthetic_home / "missing" / "..")
    result = installer._collect_preflight("none", args)
    assert not result.ready
    check = "node-storage" if field == "root" else "matter-storage"
    assert checks_by_name(result)[check].state == "fail"
    assert list(synthetic_home.iterdir()) == []



def test_preflight_dot_dot_cannot_hide_a_symlink_component(tmp_path, ready_host):
    target = tmp_path.resolve() / "separate-target"
    target.mkdir()
    (tmp_path / "linked").symlink_to(target)
    args = preflight_args(tmp_path)
    args.root = tmp_path.resolve() / "missing" / ".." / "linked" / "node"
    result = installer._collect_preflight("none", args)
    assert not result.ready
    assert checks_by_name(result)["node-storage"].state == "fail"
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("storage", [False, True])
def test_preflight_refuses_effective_service_home_when_home_is_inherited(tmp_path, ready_host, monkeypatch, storage):
    import pwd
    from types import SimpleNamespace
    service_home = tmp_path / "service-home"
    service_home.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "inherited-operator-home"))
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(service_home)))
    args = preflight_args(tmp_path, "--resume")
    if storage:
        args.storage_root = service_home
    else:
        args.root = service_home
    result = installer._collect_preflight("none", args)
    assert not result.ready
    assert checks_by_name(result)["matter-storage" if storage else "node-storage"].state == "fail"


@pytest.mark.parametrize("storage", [False, True])
@pytest.mark.parametrize("kind", ["shared", "group-writable", "nonowned", "unsafe-grandparent"])
def test_preflight_refuses_replaceable_creation_ancestors(tmp_path, ready_host, monkeypatch, storage, kind):
    parent = tmp_path / "synthetic-parent"
    parent.mkdir(mode=0o700)
    if kind == "shared":
        parent.chmod(0o777)
    elif kind == "group-writable":
        parent.chmod(0o770)
    elif kind == "unsafe-grandparent":
        parent.chmod(0o777)
        parent = parent / "private-child"
        parent.mkdir(mode=0o700)
    else:
        original = Path.stat
        def foreign_owner(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == parent:
                fields = list(result)
                fields[4] = 2000
                return os.stat_result(fields)
            return result
        monkeypatch.setattr(Path, "stat", foreign_owner)
    args = preflight_args(tmp_path)
    target = parent / "new-private-node"
    if storage:
        args.storage_root = target
    else:
        args.root = target
    result = installer._collect_preflight("none", args)
    assert checks_by_name(result)["matter-storage" if storage else "node-storage"].state == "fail"
    assert not result.ready and not target.exists()


def test_storage_chain_accepts_protected_root_parent_and_sticky_system_parent(tmp_path, ready_host, monkeypatch):
    system = tmp_path / "synthetic-system"
    system.mkdir(mode=0o755)
    creation = system / "service-owned"
    creation.mkdir(mode=0o700)
    original = Path.stat
    def root_owner(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path == system:
            fields = list(result)
            fields[4] = 0
            return os.stat_result(fields)
        return result
    monkeypatch.setattr(Path, "stat", root_owner)
    assert installer._storage_ancestors_safe(creation)
    system.chmod(0o1777)
    assert installer._storage_ancestors_safe(creation)
    assert not installer._storage_ancestors_safe(system)
    system.chmod(0o777)
    assert not installer._storage_ancestors_safe(creation)


@pytest.mark.parametrize("command", ["preflight", "install"])
def test_invalid_server_name_blocks_before_state_creation(tmp_path, ready_host, monkeypatch, command):
    node = tmp_path.resolve() / "absent-node"
    monkeypatch.setattr(sys, "argv", ["install", command, "--root", str(node),
                                     "--models", "none", "--server-name", "bad_name",
                                     "--non-interactive", "--json"] if command == "preflight" else
                                    ["install", command, "--root", str(node),
                                     "--models", "none", "--server-name", "bad_name",
                                     "--non-interactive"])
    monkeypatch.setattr(installer, "_stage_release", lambda *a, **kw: pytest.fail("invalid hostname reached release staging"))
    assert installer.main() == 1
    assert not node.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="owner-masking umask requires a real non-root permission check")
@pytest.mark.parametrize("mask", [0o000, 0o700, 0o777])
def test_prepare_protects_all_missing_storage_components_under_any_umask(tmp_path, mask):
    import stat
    base = tmp_path.resolve()
    node = base / "new-node-parent" / "nested" / "node"
    storage = base / "new-storage-parent" / "nested" / "matters"
    old_umask = os.umask(mask)
    try:
        paths = installer._prepare_directories(installer.Console(color=False, quiet=True), node,
                    storage_root=storage, resume=False, dry_run=False)
    finally:
        retained_umask = os.umask(old_umask)
    assert retained_umask == mask
    for leaf in (node, *paths.values()):
        for directory in (leaf, *leaf.parents):
            if directory == base:
                break
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700


@pytest.mark.parametrize("name", ["recordbench.example.test", "recordbench-2", "LOCALHOST"])
def test_preflight_accepts_configurable_server_name(tmp_path, ready_host, name):
    result = installer._collect_preflight("none", preflight_args(tmp_path, "--server-name", name))
    assert result.ready
    assert checks_by_name(result)["server-name"].state == "pass"
    assert name not in json.dumps(result.payload())


@pytest.mark.parametrize("kind", ["symlink", "writable", "foreign-owner"])
def test_prepare_revalidates_directory_created_during_the_walk(tmp_path, monkeypatch, kind):
    import stat
    base = tmp_path.resolve()
    target = base / "raced" / "node"
    outside = base / "outside"
    outside.mkdir(mode=0o755)
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("synthetic preserved content")
    original_mkdir, original_fstat = os.mkdir, os.fstat
    replaced_inode = None

    def concurrent_creation(path, *, dir_fd):
        nonlocal replaced_inode
        if path != "raced":
            return original_mkdir(path, 0o700, dir_fd=dir_fd)
        if kind == "symlink":
            os.symlink(outside, path, dir_fd=dir_fd)
        else:
            original_mkdir(path, 0o700, dir_fd=dir_fd)
            if kind == "writable":
                (base / path).chmod(0o777)
            replaced_inode = (base / path).stat().st_ino
        raise FileExistsError("synthetic concurrent creation")

    def foreign_owner(descriptor):
        result = original_fstat(descriptor)
        if kind == "foreign-owner" and result.st_ino == replaced_inode:
            fields = list(result)
            fields[4] = os.geteuid() + 1000
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(installer, "_mkdir_private", concurrent_creation)
    monkeypatch.setattr(os, "fstat", foreign_owner)
    with pytest.raises(RuntimeError, match="storage"):
        installer._create_private_directory(target)
    assert not (outside / "node").exists()
    assert sentinel.read_text() == "synthetic preserved content"
    assert stat.S_IMODE(outside.stat().st_mode) == 0o755
    if kind != "symlink":
        assert not target.exists()


@pytest.mark.parametrize("storage", [False, True])
def test_prepare_refuses_symlink_in_selected_storage_path(tmp_path, storage):
    base = tmp_path.resolve()
    outside = base / "outside"
    outside.mkdir()
    linked = base / "linked"
    linked.symlink_to(outside)
    node = base / "node" if storage else linked / "node"
    with pytest.raises(RuntimeError, match="symbolic link"):
        installer._prepare_directories(installer.Console(color=False, quiet=True), node,
            storage_root=linked / "matters" if storage else None, resume=False, dry_run=False)
    assert list(outside.iterdir()) == []
    assert not (base / "node").exists()


def test_prepare_revalidates_existing_parent_without_changing_it(tmp_path):
    import stat
    parent = tmp_path.resolve() / "parent"
    parent.mkdir(mode=0o755)
    node = parent / "node"
    parent.chmod(0o777)
    with pytest.raises(RuntimeError, match="replaceable"):
        installer._prepare_directories(installer.Console(color=False, quiet=True), node,
            storage_root=None, resume=False, dry_run=False)
    assert not node.exists()
    assert stat.S_IMODE(parent.stat().st_mode) == 0o777
    parent.chmod(0o755)
    installer._prepare_directories(installer.Console(color=False, quiet=True), node,
        storage_root=None, resume=False, dry_run=False)
    assert stat.S_IMODE(parent.stat().st_mode) == 0o755
    assert stat.S_IMODE(node.stat().st_mode) == 0o700


def test_prepare_resume_does_not_follow_replaced_internal_directory(tmp_path):
    base = tmp_path.resolve()
    node = base / "node"
    node.mkdir(mode=0o700)
    outside = base / "outside"
    outside.mkdir()
    (node / "config").symlink_to(outside)
    with pytest.raises(RuntimeError, match="safely"):
        installer._prepare_directories(installer.Console(color=False, quiet=True), node,
            storage_root=None, resume=True, dry_run=False)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("blocker", ["capacity", "creation-parent"])
def test_preflight_json_reports_real_host_blockers_without_creating_state(tmp_path, ready_host, monkeypatch, capsys, blocker):
    parent = tmp_path.resolve() / "creation-parent"
    parent.mkdir(mode=0o700)
    root = parent / "uncreated node"
    if blocker == "capacity":
        monkeypatch.setattr(installer.shutil, "disk_usage", lambda path: type("Disk", (), {"free": 99 * 1024**3})())
        blocked_check = "node-storage-reserve"
    else:
        parent.chmod(0o1777)
        blocked_check = "node-storage"
    monkeypatch.setattr(sys, "argv", ["install", "preflight", "--root", str(root), "--models", "none", "--json"])
    assert installer.main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ready"] is False
    assert payload["schema_version"] == 1
    check = next(row for row in payload["checks"] if row["name"] == blocked_check)
    assert check["blocking"] is True and check["state"] == "fail" and check["remedy"]
    assert all(row["remedy"] for row in payload["checks"] if row["blocking"] and row["state"] != "pass")
    assert not root.exists()
    assert list(parent.iterdir()) == []


def test_interactive_invalid_hostname_blocks_before_storage_and_release(tmp_path, ready_host, monkeypatch):
    node = tmp_path.resolve() / "uncreated node"
    prompts = []

    def ask(prompt, default, *, non_interactive):
        prompts.append(prompt)
        return "bad_name" if prompt == "RecordBench hostname" else default

    monkeypatch.setattr(installer, "_ask", ask)
    monkeypatch.setattr(installer, "_prepare_directories", lambda *a, **kw: pytest.fail("invalid interactive hostname reached storage creation"))
    monkeypatch.setattr(installer, "_stage_release", lambda *a, **kw: pytest.fail("invalid interactive hostname reached release staging"))
    monkeypatch.setattr(sys, "argv", ["install", "--root", str(node), "--models", "none", "--auth", "local"])
    assert installer.main() == 1
    assert prompts.count("RecordBench hostname") == 1
    assert not node.exists()


@pytest.mark.parametrize("storage", [False, True])
def test_preflight_rejects_execute_only_ancestor_before_preparing_storage(tmp_path, ready_host, monkeypatch, storage):
    base = tmp_path.resolve()
    protected = base / "execute-only-parent"
    protected.mkdir(mode=0o711)
    creation = protected / "service-owned"
    creation.mkdir(mode=0o700)
    original_stat, original_access = Path.stat, os.access

    def synthetic_root_owner(path, *args, **kwargs):
        metadata = original_stat(path, *args, **kwargs)
        if path == protected:
            fields = list(metadata)
            fields[4] = 0
            return os.stat_result(fields)
        return metadata

    def service_access(path, mode, *args, **kwargs):
        if Path(path) == protected:
            return not bool(mode & (os.R_OK | os.W_OK))
        return original_access(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", synthetic_root_owner)
    monkeypatch.setattr(os, "access", service_access)
    args = preflight_args(tmp_path)
    selected = creation / "uncreated"
    if storage:
        args.storage_root = selected
    else:
        args.root = selected
    result = installer._collect_preflight("none", args)
    assert not result.ready
    check = checks_by_name(result)["matter-storage" if storage else "node-storage"]
    assert check.state == "fail" and check.remedy
    assert not selected.exists()
    assert list(creation.iterdir()) == []
    monkeypatch.setattr(os, "access", original_access)
    assert installer._collect_preflight("none", args).ready
    assert not selected.exists()


def test_interactive_hostname_is_collected_once_and_used_by_configuration(tmp_path, ready_host, monkeypatch):
    node = tmp_path.resolve() / "uncreated node"
    prompts = []
    original_configure = installer._configure

    def ask(prompt, default, *, non_interactive):
        prompts.append(prompt)
        return "synthetic-node.example.test" if prompt == "RecordBench hostname" else default

    def configure(console, args, *positional, **kwargs):
        assert args.server_name == "synthetic-node.example.test"
        return original_configure(console, args, *positional, **kwargs)

    monkeypatch.setattr(installer, "_ask", ask)
    monkeypatch.setattr(installer, "_configure", configure)
    monkeypatch.setattr(sys, "argv", ["install", "--root", str(node), "--models", "none", "--auth", "local", "--dry-run"])
    assert installer.main() == 0
    assert prompts.count("RecordBench hostname") == 1
    assert not node.exists()


@pytest.mark.parametrize("prompt,value", [
    ("Initial administrator username", "bad/name"),
    ("Administrator display name", "bad\nname"),
    ("Administrator display name", "   "),
    ("Administrator display name", "x" * 161),
])
def test_interactive_identity_is_validated_before_any_writes(tmp_path, ready_host, monkeypatch, prompt, value):
    node = tmp_path.resolve() / "uncreated-node"
    monkeypatch.setattr(installer, "_ask", lambda label, default, **k: value if label == prompt else default)
    monkeypatch.setattr(installer, "_choose", lambda *a, **k: "local")
    monkeypatch.setattr(installer, "_prepare_directories", lambda *a, **k: pytest.fail("interactive identity reached writes"))
    monkeypatch.setattr(installer.getpass, "getpass", lambda *a: pytest.fail("identity preflight read a secret"))
    monkeypatch.setattr(sys, "argv", ["install", "--root", str(node), "--models", "none"])
    assert installer.main() == 1
    assert not node.exists()


@pytest.mark.parametrize("auth,prompt", [("oidc", "OIDC client ID"), ("kerberos", "Kerberos realm")])
def test_interactive_provider_text_is_checked_before_writes(tmp_path, ready_host, monkeypatch, auth, prompt):
    node = tmp_path.resolve() / "uncreated-node"
    monkeypatch.setattr(installer, "_ask", lambda label, default, **k: "bad\nvalue" if label == prompt else default)
    monkeypatch.setattr(installer, "_choose", lambda *a, **k: auth)
    monkeypatch.setattr(installer, "_prepare_directories", lambda *a, **k: pytest.fail("invalid provider text reached writes"))
    monkeypatch.setattr(sys, "argv", ["install", "--root", str(node), "--models", "none", "--dry-run"])
    assert installer.main() == 1
    assert not node.exists()


@pytest.mark.parametrize("missing", ["host", "keytab"])
def test_interactive_kerberos_checks_actual_choice_before_any_writes(tmp_path, ready_host, monkeypatch, missing):
    node = tmp_path.resolve() / "uncreated-node"
    keytab = tmp_path / "synthetic-keytab"
    if missing == "host":
        keytab.write_text("synthetic placeholder")
    prompts = []
    def ask(label, default, **kwargs):
        prompts.append(label)
        return str(keytab) if label == "Path to the exported HTTP service keytab" else default
    original_is_dir, original_is_file = Path.is_dir, Path.is_file
    monkeypatch.setattr(Path, "is_dir", lambda path: missing != "host" if path == Path("/var/lib/sss/pipes") else original_is_dir(path))
    monkeypatch.setattr(Path, "is_file", lambda path: True if path == Path("/etc/krb5.conf") else original_is_file(path))
    monkeypatch.setattr(installer, "_ask", ask)
    monkeypatch.setattr(installer, "_choose", lambda *a, **k: "kerberos")
    monkeypatch.setattr(installer, "_prepare_directories", lambda *a, **k: pytest.fail("interactive Kerberos choice reached writes"))
    monkeypatch.setattr(installer.getpass, "getpass", lambda *a: pytest.fail("identity preflight read a secret"))
    monkeypatch.setattr(sys, "argv", ["install", "--root", str(node), "--models", "none"])
    assert installer.main() == 1
    assert prompts.count("Path to the exported HTTP service keytab") == 1
    assert not node.exists()


@pytest.mark.parametrize("auth", ["local", "oidc", "kerberos"])
def test_configuration_reuses_all_preflight_identity_answers(tmp_path, ready_host, monkeypatch, auth):
    node = tmp_path.resolve() / "uncreated-node"
    prompts = []
    def ask(label, default, **kwargs):
        prompts.append(label)
        return default
    original_configure = installer._configure
    def configure(console, args, *positional, **kwargs):
        assert args.auth == auth
        monkeypatch.setattr(installer, "_ask", lambda *a, **k: pytest.fail("configuration asked an unchecked identity question"))
        monkeypatch.setattr(installer, "_choose", lambda *a, **k: pytest.fail("configuration changed the checked identity mode"))
        return original_configure(console, args, *positional, **kwargs)
    monkeypatch.setattr(installer, "_ask", ask)
    monkeypatch.setattr(installer, "_choose", lambda *a, **k: auth)
    monkeypatch.setattr(installer, "_configure", configure)
    monkeypatch.setattr(installer.getpass, "getpass", lambda *a: pytest.fail("dry-run read a secret"))
    monkeypatch.setattr(sys, "argv", ["install", "--root", str(node), "--models", "none", "--dry-run"])
    assert installer.main() == 0
    assert len(prompts) == len(set(prompts))
    assert not node.exists()


@pytest.mark.parametrize("models", ["transcription", "all"])
@pytest.mark.parametrize("flags,missing", [
    ([], {"model-terms", "model-token-input"}),
    (["--accept-model-terms"], {"model-token-input"}),
    (["--hf-token-stdin"], {"model-terms"}),
])
def test_unattended_diarization_blocks_missing_staging_options_before_writes(
    tmp_path, ready_host, monkeypatch, models, flags, missing,
):
    node = tmp_path.resolve() / "uncreated node"
    def probe(command):
        output = ("0, Synthetic GPU, 49152, 47000, 8.9" if command[0] == "nvidia-smi"
                  else '{"nvidia": {}}' if "{{json .Runtimes}}" in command else "1.0")
        return subprocess.CompletedProcess(command, 0, output, "")
    monkeypatch.setattr(installer, "_probe", probe)
    monkeypatch.setattr(installer, "_hf_token", lambda *a: pytest.fail("preflight read a token"))
    monkeypatch.setattr(installer, "_prepare_directories", lambda *a, **k: pytest.fail("missing staging choices reached writes"))
    args = installer._parser().parse_args(["install", "--root", str(node), "--models", models,
                                          "--enable-diarization", "--non-interactive", "--password-stdin", *flags])
    result = installer._collect_preflight(models, args)
    assert {row.name for row in result.checks if row.blocking and row.state == "fail"} == missing
    monkeypatch.setattr(sys, "argv", ["install", "--root", str(node), "--models", models,
                                     "--enable-diarization", "--non-interactive", "--password-stdin", *flags])
    assert installer.main() == 1
    assert not node.exists()


def test_diarization_preflight_checks_flags_without_consuming_standard_input(tmp_path, ready_host, monkeypatch):
    class UnreadInput:
        def readline(self, *args):
            pytest.fail("preflight must not consume the staging token")
    monkeypatch.setattr(sys, "stdin", UnreadInput())
    monkeypatch.setattr(installer, "_probe", lambda command: subprocess.CompletedProcess(command, 0,
        "0, Synthetic GPU, 49152, 47000, 8.9" if command[0] == "nvidia-smi" else '{"nvidia": {}}', ""))
    args = preflight_args(tmp_path, "--models", "transcription", "--enable-diarization", "--non-interactive",
                          "--accept-model-terms", "--hf-token-stdin", "--password-stdin")
    result = installer._collect_preflight("transcription", args)
    assert result.ready
    assert checks_by_name(result)["model-token-input"].state == "pass"


def saved_gpu_node(tmp_path, *, model_profile="quality", models="review"):
    root = tmp_path.resolve() / "saved-node"
    (root / "config").mkdir(parents=True)
    installation = {
        "release_id": "synthetic", "release_path": str(ROOT), "auth": "local", "models": models,
        "profiles": ["ai"] if models == "review" else ["transcription"],
        "review_model_profile": model_profile, "gpu_layout": "shared",
        "gpu_topology": {"generator": ["0"], "transcription": "0", "retrieval_device": "cpu", "retrieval_gpu": None},
    }
    (root / "installation.json").write_text(json.dumps(installation))
    environment = {"RECORDBENCH_GENERATOR_GPU": "0", "RECORDBENCH_TRANSCRIPTION_GPU": "0",
                   "RECORDBENCH_RETRIEVAL_DEVICE": "cpu", "RECORDBENCH_RETRIEVAL_GPU": "0",
                   "RECORDBENCH_GPU_LAYOUT": "shared", "RECORDBENCH_GENERATOR_GPU_UTILIZATION": "0.72"}
    (root / "compose.env").write_text(installer._env_text(environment, "synthetic saved GPU plan"))
    (root / "config" / "transcription.env").write_text('TRANSCRIPTION_V2_MIN_FREE_VRAM_MB="16000"\n')
    return root, installation, environment


@pytest.mark.parametrize("auth", [[], ["--auth", "local"]])
@pytest.mark.parametrize("resume", [[], ["--resume"]])
def test_fresh_local_unattended_password_choice_blocks_before_writes(
    tmp_path, ready_host, monkeypatch, capsys, auth, resume,
):
    node = tmp_path.resolve() / "uncreated-node"
    flags = ["--root", str(node), "--models", "none", "--non-interactive", *auth, *resume]
    monkeypatch.setattr(installer, "_prepare_directories", lambda *a, **k: pytest.fail("password choice reached writes"))
    monkeypatch.setattr(installer, "_password", lambda *a: pytest.fail("preflight read a password"))
    monkeypatch.setattr(sys, "argv", ["install", "preflight", "--json", *flags])
    assert installer.main() == 1
    payload = json.loads(capsys.readouterr().out)
    failed = [row for row in payload["checks"] if row["blocking"] and row["state"] == "fail"]
    assert [row["name"] for row in failed] == ["admin-password-input"]
    assert "--password-stdin" in failed[0]["remedy"]
    monkeypatch.setattr(sys, "argv", ["install", *flags])
    assert installer.main() == 1
    assert not node.exists()


@pytest.mark.parametrize("options", [["--password-stdin"], ["--dry-run"], ["--auth", "oidc", "--dry-run"], ["--auth", "kerberos", "--dry-run"]])
def test_unattended_password_preflight_accepts_available_input_without_reading(
    tmp_path, ready_host, monkeypatch, options,
):
    class UnreadInput:
        def readline(self, *args):
            pytest.fail("preflight must not consume the password")
    monkeypatch.setattr(sys, "stdin", UnreadInput())
    args = preflight_args(tmp_path, "--non-interactive", *options)
    assert installer._collect_preflight("none", args).ready
    assert not args.root.exists()


@pytest.mark.parametrize("flags,check", [
    (["--admin-username", "bad/name"], "admin-identity"),
    (["--admin-username", "ab"], "admin-identity"),
    (["--admin-display-name", "   "], "admin-identity"),
    (["--admin-display-name", "synthetic\nname"], "admin-identity"),
    (["--admin-display-name", "x" * 161], "admin-identity"),
    (["--auth", "oidc"], "oidc-secret-input"),
    (["--auth", "oidc", "--oidc-client-secret-file", "/missing/synthetic-secret"], "oidc-secret-input"),
    (["--auth", "kerberos"], "kerberos-keytab-input"),
])
def test_invalid_identity_inputs_block_fresh_install_before_writes(
    tmp_path, ready_host, monkeypatch, flags, check,
):
    args = preflight_args(tmp_path, "--non-interactive", "--password-stdin", *flags)
    assert checks_by_name(installer._collect_preflight("none", args))[check].state == "fail"
    monkeypatch.setattr(installer, "_prepare_directories", lambda *a, **k: pytest.fail("invalid identity reached writes"))
    monkeypatch.setattr(sys, "argv", ["install", "--root", str(args.root), "--models", "none",
                                     "--non-interactive", "--password-stdin", *flags])
    assert installer.main() == 1
    assert not args.root.exists()


@pytest.mark.parametrize("kind", ["regular", "empty", "large", "directory", "symlink"])
def test_oidc_credential_preflight_checks_metadata_without_reading(tmp_path, ready_host, monkeypatch, kind):
    source = tmp_path / "synthetic-secret"
    if kind == "directory":
        source.mkdir()
    elif kind == "symlink":
        target = tmp_path / "synthetic-target"
        target.write_text("synthetic placeholder")
        source.symlink_to(target)
    else:
        source.write_text("" if kind == "empty" else "x" * (1024 * 1024 + 1) if kind == "large" else "synthetic placeholder")
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: pytest.fail("preflight read a credential"))
    monkeypatch.setattr(Path, "read_bytes", lambda *a, **k: pytest.fail("preflight read a credential"))
    args = preflight_args(tmp_path, "--auth", "oidc", "--non-interactive", "--oidc-client-secret-file", str(source))
    result = installer._collect_preflight("none", args)
    assert checks_by_name(result)["oidc-secret-input"].state == ("pass" if kind == "regular" else "fail")
    assert result.ready is (kind == "regular")
    assert str(source) not in json.dumps(result.payload())
    assert not args.root.exists()


def test_local_identity_preflight_accepts_account_admin_normalization(tmp_path, ready_host):
    args = preflight_args(tmp_path, "--non-interactive", "--password-stdin", "--admin-username", " Synthetic.ADMIN ",
                          "--admin-display-name", " Synthetic Administrator ")
    assert installer._collect_preflight("none", args).ready


@pytest.mark.parametrize("dtype,compute", [("half", 7.5), ("half", 8.9), ("bfloat16", 8.0)])
def test_supported_saved_generator_precision_is_preserved(tmp_path, dtype, compute):
    root, installation, environment = saved_gpu_node(tmp_path)
    environment["RECORDBENCH_GENERATOR_DTYPE"] = dtype
    args = installer._parser().parse_args(["install", "--root", str(root)])
    installer._restore_model_options(args, installation, environment, {})
    _, plan = installer._resolve_gpu_plans(args, "review", (installer.GpuDevice("0", "Synthetic GPU", 49152, 47000, compute),))
    assert plan.dtype == dtype


def test_fresh_diarization_dry_run_never_consumes_credentials(tmp_path, ready_host, monkeypatch):
    node = tmp_path.resolve() / "uncreated-node"
    monkeypatch.setattr(installer, "_probe", lambda cmd: subprocess.CompletedProcess(cmd, 0,
        "0, Synthetic GPU, 49152, 47000, 8.9" if cmd[0] == "nvidia-smi" else '{"nvidia": {}}', ""))
    monkeypatch.setattr(installer, "_hf_token", lambda *a: pytest.fail("dry-run consumed a token"))
    monkeypatch.setattr(installer, "_password", lambda *a: pytest.fail("dry-run consumed a password"))
    monkeypatch.setattr(sys, "argv", ["install", "--root", str(node), "--models", "transcription", "--enable-diarization",
                                     "--non-interactive", "--accept-model-terms", "--hf-token-stdin", "--dry-run"])
    assert installer.main() == 0
    assert not node.exists()


def test_relative_node_root_has_same_blocking_result_in_preflight_and_install(
    tmp_path, ready_host, monkeypatch, capsys,
):
    monkeypatch.chdir(tmp_path.resolve())
    flags = ["--root", "relative-node", "--models", "none", "--non-interactive", "--dry-run"]
    monkeypatch.setattr(installer, "_prepare_directories", lambda *a, **k: pytest.fail("relative root reached writes"))
    monkeypatch.setattr(sys, "argv", ["install", "preflight", "--json", *flags])
    assert installer.main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert next(row for row in payload["checks"] if row["name"] == "node-storage")["state"] == "fail"
    monkeypatch.setattr(sys, "argv", ["install", *flags])
    assert installer.main() == 1
    assert not (tmp_path / "relative-node").exists()


@pytest.mark.parametrize("command", ["resume", "update"])
@pytest.mark.parametrize("dtype", ["bfloat16", None])
def test_saved_bfloat16_blocks_older_replacement_gpu_before_commands(
    tmp_path, ready_host, monkeypatch, command, dtype,
):
    root, installation, environment = saved_gpu_node(tmp_path)
    if dtype is not None:
        environment["RECORDBENCH_GENERATOR_DTYPE"] = dtype
    (root / "compose.env").write_text(installer._env_text(environment, "synthetic saved precision"))
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    monkeypatch.setattr(installer, "_probe", lambda cmd: subprocess.CompletedProcess(cmd, 0,
        "0, Synthetic Replacement GPU, 49152, 47000, 7.5" if cmd[0] == "nvidia-smi" else '{"nvidia": {}}', ""))
    assert installer._collect_preflight("review").ready
    monkeypatch.setattr(installer, "_run", lambda *a, **k: pytest.fail("unsupported saved precision reached a command"))
    monkeypatch.setattr(installer, "_stage_release", lambda *a, **k: pytest.fail("unsupported saved precision staged a release"))
    args = installer._parser().parse_args(["install" if command == "resume" else "update", "--root", str(root),
                                          "--non-interactive", "--no-backup"])
    action = installer._resume_node if command == "resume" else installer._update
    with pytest.raises(RuntimeError, match="prerequisites"):
        action(installer.Console(color=False, quiet=True), args, root)
    assert {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("command,shortage", [
    (command, shortage) for command in ("resume", "update")
    for shortage in ("explicit-device", "quality-model", "utilization", "transcription")
    if command != "update" or shortage not in {"explicit-device", "utilization"}
])
def test_saved_gpu_preflight_blocks_resume_update_before_commands(
    tmp_path, ready_host, monkeypatch, command, shortage,
):
    models = "transcription" if shortage == "transcription" else "review"
    root, installation, environment = saved_gpu_node(tmp_path, models=models)
    inventories = {
        "explicit-device": "0, Synthetic Busy, 49152, 1000, 8.9\n1, Synthetic Free, 49152, 47000, 8.9",
        "quality-model": "0, Synthetic Small, 24576, 24000, 8.0",
        "utilization": "0, Synthetic Partial, 49152, 35000, 8.9",
        "transcription": "0, Synthetic Transcription, 49152, 44000, 8.9",
    }
    if shortage == "utilization":
        environment["RECORDBENCH_GENERATOR_GPU_UTILIZATION"] = "0.90"
        (root / "compose.env").write_text(installer._env_text(environment, "synthetic saved reservation"))
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    monkeypatch.setattr(installer, "_probe", lambda cmd: subprocess.CompletedProcess(cmd, 0,
        inventories[shortage] if cmd[0] == "nvidia-smi" else '{"nvidia": {}}', ""))
    # Demonstrate why checking an automatic plan is insufficient: it can pass by
    # selecting a different GPU, smaller model, or smaller reservation.
    assert installer._collect_preflight(models).ready
    monkeypatch.setattr(installer, "_run", lambda *a, **k: pytest.fail("blocked saved plan reached a command"))
    monkeypatch.setattr(installer, "_stage_release", lambda *a, **k: pytest.fail("blocked saved plan staged a release"))
    args = installer._parser().parse_args(["install" if command == "resume" else "update", "--root", str(root),
                                          "--non-interactive", "--no-backup", "--generator-gpus", "1",
                                          "--review-model-profile", "portable"])
    action = installer._resume_node if command == "resume" else installer._update
    with pytest.raises(RuntimeError, match="prerequisites"):
        action(installer.Console(color=False, quiet=True), args, root)
    assert args.generator_gpus == "0" and args.review_model_profile == "quality"
    assert {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()} == before


def test_completed_diarization_resume_uses_saved_plan_without_new_token(tmp_path, ready_host, monkeypatch):
    root, installation, environment = saved_gpu_node(tmp_path, model_profile="portable", models="transcription")
    installation["transcription_diarization"] = True
    installation["transcription_languages"] = ["en", "es"]
    environment["RECORDBENCH_TRANSCRIPTION_GPU"] = "1"
    (root / "installation.json").write_text(json.dumps(installation))
    (root / "compose.env").write_text(installer._env_text(environment, "synthetic saved transcription"))
    (root / "state").mkdir()
    installer._seal_provisioning(root, installation)
    monkeypatch.setattr(installer, "_probe", lambda cmd: subprocess.CompletedProcess(cmd, 0,
        "0, Synthetic Busy, 24576, 1000, 8.0\n1, Synthetic Selected, 24576, 24000, 8.0"
        if cmd[0] == "nvidia-smi" else '{"nvidia": {}}', ""))
    commands = []
    monkeypatch.setattr(installer, "_run", lambda console, cmd, **kw: commands.append(cmd))
    monkeypatch.setattr(installer, "_hf_token", lambda *a: pytest.fail("completed resume must remain offline"))
    args = installer._parser().parse_args(["install", "--root", str(root), "--resume", "--non-interactive", "--dry-run"])
    installer._resume_node(installer.Console(color=False, quiet=True), args, root)
    assert len(commands) == 2 and "up" in commands[-1]
    assert args.transcription_gpu == "1" and args.transcription_languages == "en,es"
    assert args.transcription_min_free_vram_mib == 16000

@pytest.mark.parametrize("record", [None, [], {"auth": "unsupported", "models": "none"}, {"auth": []}, {"auth": "local", "models": {}}, {"auth": "local", "profiles": [3]}])
def test_resume_unrelated_root_stops_before_writes(tmp_path, ready_host, monkeypatch, record):
    node = tmp_path.resolve() / "unrelated"
    node.mkdir()
    sentinel = node / "compose.env"
    sentinel.write_text("synthetic existing data")
    if record is not None:
        (node / "installation.json").write_text(json.dumps(record))
    before = {path.name: path.read_bytes() for path in node.iterdir()}
    args = preflight_args(tmp_path, "--root", str(node), "--resume")
    assert not installer._collect_preflight("none", args).ready
    monkeypatch.setattr(installer, "_prepare_directories", lambda *a, **k: pytest.fail("prepared storage"))
    monkeypatch.setattr(installer, "_run", lambda *a, **k: pytest.fail("ran install command"))
    monkeypatch.setattr(sys, "argv", ["install", "--root", str(node), "--resume", "--models", "none", "--non-interactive", "--password-stdin"])
    assert installer.main() == 1
    assert {path.name: path.read_bytes() for path in node.iterdir()} == before


@pytest.mark.parametrize("reserved", ["matters", ".matter-purging", "ingestion-staging"])
@pytest.mark.parametrize("kind", ["directory", "file", "broken-link"])
def test_preflight_reserved_storage_collision_stops_install(tmp_path, ready_host, monkeypatch, reserved, kind):
    storage = tmp_path.resolve() / "storage"
    storage.mkdir()
    entry = storage / reserved
    if kind == "directory":
        entry.mkdir()
    elif kind == "file":
        entry.write_text("synthetic unrelated data")
    else:
        entry.symlink_to(storage / "missing")
    args = preflight_args(tmp_path, "--storage-root", str(storage))
    result = installer._collect_preflight("none", args)
    assert not result.ready
    assert checks_by_name(result)["matter-storage-layout"].state == "fail"
    monkeypatch.setattr(installer, "_prepare_directories", lambda *a, **k: pytest.fail("prepared storage"))
    monkeypatch.setattr(sys, "argv", ["install", "--root", str(args.root), "--storage-root", str(storage), "--models", "none", "--non-interactive", "--password-stdin"])
    assert installer.main() == 1
    assert not args.root.exists()
    assert list(storage.iterdir()) == [entry]


@pytest.mark.parametrize("auth,option,value", [
    ("oidc", "--oidc-issuer", "http://identity.example.test"),
    ("kerberos", "--kerberos-realm", "EXAMPLE"),
])
def test_provider_semantics_stop_install_before_writes(tmp_path, ready_host, monkeypatch, auth, option, value):
    args = preflight_args(tmp_path, "--auth", auth, option, value, "--dry-run")
    result = installer._collect_preflight("none", args)
    assert not result.ready
    assert checks_by_name(result)["identity-options"].state == "fail"
    monkeypatch.setattr(installer, "_prepare_directories", lambda *a, **k: pytest.fail("prepared storage"))
    monkeypatch.setattr(sys, "argv", ["install", "--root", str(args.root), "--models", "none", "--auth", auth, option, value, "--non-interactive", "--dry-run"])
    assert installer.main() == 1
    assert not args.root.exists()


@pytest.mark.parametrize("bind", ["127.0.0.1\nINJECTED=1", "example.test", "127.0.0.1:8443", "[::1]", "", "2001:db8::1%eth0\nINJECTED=1", "2001:db8::1%eth0"])
def test_bind_literal_with_tls_stops_before_writes(tmp_path, ready_host, monkeypatch, bind):
    cert, key = tmp_path / "synthetic.crt", tmp_path / "synthetic.key"
    cert.write_text("synthetic certificate")
    key.write_text("synthetic key")
    options = ["--bind-address", bind, "--tls-cert", str(cert), "--tls-key", str(key)]
    args = preflight_args(tmp_path, *options)
    result = installer._collect_preflight("none", args)
    assert not result.ready
    assert checks_by_name(result)["bind-address"].state == "fail"
    monkeypatch.setattr(installer, "_prepare_directories", lambda *a, **k: pytest.fail("prepared storage"))
    monkeypatch.setattr(sys, "argv", ["install", "--root", str(args.root), "--models", "none", "--non-interactive", "--password-stdin", *options])
    assert installer.main() == 1
    assert not args.root.exists()

@pytest.mark.parametrize("bind", ["127.0.0.1", "0.0.0.0", "192.0.2.10", "::1", "2001:db8::10"])
def test_preflight_accepts_ip_bind_literals(tmp_path, ready_host, bind):
    args = preflight_args(tmp_path, "--bind-address", bind)
    assert checks_by_name(installer._collect_preflight("none", args))["bind-address"].state == "pass"


def test_preflight_preserves_initialized_storage_without_writes(tmp_path, ready_host, monkeypatch):
    storage = tmp_path.resolve() / "storage"
    storage.mkdir()
    for name in ("matters", ".matter-purging", "ingestion-staging"):
        (storage / name).mkdir()
    marker = storage / ".recordbench-managed-storage.json"
    marker.write_text(json.dumps({"format_version": 1, "product": "RecordBench", "storage_id": "recordbench-storage-synthetic"}))
    (storage / "matters" / "synthetic.txt").write_text("synthetic matter fixture")
    args = preflight_args(tmp_path, "--storage-root", str(storage))
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: pytest.fail("preflight wrote storage"))
    assert installer._collect_preflight("none", args).ready
    marker.write_text("[]")
    assert checks_by_name(installer._collect_preflight("none", args))["matter-storage-layout"].state == "fail"


@pytest.mark.parametrize("auth,options,expected", [
    ("oidc", [], True),
    ("oidc", ["--oidc-issuer", "https://identity.example.test/realm/"], True),
    ("oidc", ["--oidc-issuer", "http://identity.example.test"], False),
    ("oidc", ["--oidc-issuer", "https://identity.example.test?query=yes"], False),
    ("oidc", ["--oidc-issuer", "https://identity.example.test/#fragment"], False),
    ("oidc", ["--oidc-issuer", "https://user:pass@identity.example.test"], False),
    ("oidc", ["--oidc-issuer", "https://localhost"], False),
    ("oidc", ["--oidc-issuer", "https://127.0.0.1"], False),
    ("oidc", ["--server-name", "localhost"], False),
    ("oidc", ["--server-name", "127.0.0.1"], False),
    ("oidc", ["--server-name", " RecordBench.Example.Test "], True),
    ("oidc", ["--oidc-issuer", "https://identity.example.test/" + "a" * 1024], False),
    ("oidc", ["--oidc-client-id", ""], False),
    ("oidc", ["--oidc-client-id", "a\tb"], False),
    ("oidc", ["--oidc-client-id", "a" * 513], False),
    ("oidc", ["--oidc-allowed-groups", "a" * 257], False),
    ("oidc", ["--oidc-admin-groups", ",".join(f"group{i}" for i in range(51))], False),
    ("oidc", ["--oidc-allowed-groups", ",".join(f"group{i}" for i in range(101))], False),
    ("oidc", ["--oidc-allowed-groups", "", "--oidc-admin-groups", ""], True),
    ("oidc", ["--oidc-allowed-groups", "Team,team"], True),
    ("kerberos", [], True),
    ("kerberos", ["--kerberos-realm", " example.test "], True),
    ("kerberos", ["--kerberos-realm", "EXAMPLE"], False),
    ("kerberos", ["--kerberos-realm=-EXAMPLE.TEST"], False),
    ("kerberos", ["--kerberos-realm", "a" * 250 + ".test"], False),
    ("kerberos", ["--kerberos-allowed-groups", "team/invalid"], False),
    ("kerberos", ["--kerberos-allowed-groups", "a" * 256], False),
    ("kerberos", ["--kerberos-allowed-groups", "", "--kerberos-admin-groups", ""], False),
    ("kerberos", ["--kerberos-allowed-groups", "", "--kerberos-admin-groups", "Team Admins"], True),
    ("kerberos", ["--kerberos-admin-groups", ",".join(f"group{i}" for i in range(51))], False),
    ("kerberos", ["--kerberos-allowed-groups", ",".join(f"group{i}" for i in range(101))], False),
    ("kerberos", ["--kerberos-allowed-groups", "Team,team"], True),
])
def test_preflight_nonsecret_settings_match_identity_runtime(tmp_path, ready_host, auth, options, expected):
    from case_intelligence.identity import KerberosSettings, OidcSettings
    args = preflight_args(tmp_path, "--auth", auth, "--dry-run", *options)
    values = {name: getattr(args, name) if getattr(args, name) is not None else default
              for name, _prompt, default in installer.IDENTITY_FIELDS[auth]}
    groups = {suffix: frozenset(value.strip() for value in values[f"{auth}_{suffix}"].split(",") if value.strip())
              for suffix in ("allowed_groups", "admin_groups")}
    try:
        if auth == "oidc":
            OidcSettings(issuer=values["oidc_issuer"],
                         external_origin=f"https://{installer._valid_host(args.server_name or 'recordbench.example.test')}:{args.https_port}",
                         client_id=values["oidc_client_id"], client_secret="synthetic-secret-value",
                         allowed_groups=groups["allowed_groups"], administrator_groups=groups["admin_groups"])
        else:
            KerberosSettings(realm=values["kerberos_realm"], proxy_secret="synthetic-secret-value-0123456789abcdef",
                             allowed_groups=groups["allowed_groups"], administrator_groups=groups["admin_groups"])
        runtime_valid = True
    except (RuntimeError, ValueError):
        runtime_valid = False
    assert runtime_valid is expected
    result = installer._collect_preflight("none", args)
    assert (checks_by_name(result)["identity-options"].state == "pass") is runtime_valid
    assert not args.root.exists()

@pytest.mark.parametrize("relative", ["compose.env", "installation.json", "config/recordbench.env", "releases/capsule", "state"])
def test_matter_storage_control_path_overlap_stops_before_writes(tmp_path, ready_host, monkeypatch, relative):
    node = tmp_path.resolve() / "new-node"
    flags = ["--root", str(node), "--storage-root", str(node / relative), "--models", "none", "--non-interactive", "--password-stdin"]
    args = installer._parser().parse_args(["preflight", *flags])
    assert not installer._collect_preflight("none", args).ready
    monkeypatch.setattr(installer, "_prepare_directories", lambda *a, **k: pytest.fail("overlap reached writes"))
    monkeypatch.setattr(sys, "argv", ["install", *flags])
    assert installer.main() == 1
    assert not node.exists()


@pytest.mark.parametrize("field", ["--root", "--storage-root"])
@pytest.mark.parametrize("control", ["\n", "\r", "\t", "\x7f", "\x00"])
def test_storage_control_characters_stop_before_writes(tmp_path, ready_host, monkeypatch, field, control):
    node = tmp_path.resolve() / "new-node"
    malformed = str(tmp_path.resolve() / ("synthetic" + control + "path"))
    flags = ["--root", str(node), field, malformed, "--models", "none", "--non-interactive", "--password-stdin"]
    args = installer._parser().parse_args(["preflight", *flags])
    assert not installer._collect_preflight("none", args).ready
    monkeypatch.setattr(installer, "_prepare_directories", lambda *a, **k: pytest.fail("invalid path reached writes"))
    monkeypatch.setattr(sys, "argv", ["install", *flags])
    assert installer.main() == 1
    assert not node.exists() and not Path(malformed).exists()


def test_oversized_oidc_secret_stops_before_writes_without_reading(tmp_path, ready_host, monkeypatch):
    source = tmp_path / "synthetic-secret"
    source.write_text("x" * 4097)
    args = preflight_args(tmp_path, "--auth", "oidc", "--non-interactive", "--oidc-client-secret-file", str(source))
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: pytest.fail("read credential contents"))
    monkeypatch.setattr(Path, "read_bytes", lambda *a, **k: pytest.fail("read credential contents"))
    assert not installer._collect_preflight("none", args).ready
    monkeypatch.setattr(installer, "_prepare_directories", lambda *a, **k: pytest.fail("oversized secret reached writes"))
    monkeypatch.setattr(sys, "argv", ["install", "--root", str(args.root), "--models", "none", "--auth", "oidc", "--oidc-client-secret-file", str(source), "--non-interactive"])
    assert installer.main() == 1
    assert not args.root.exists()


def synthetic_live_update(tmp_path, monkeypatch, *, after_free=47000, fail_command=None, dry_run=False, utilization="0.72"):
    root, installation, environment = saved_gpu_node(tmp_path)
    environment["RECORDBENCH_GENERATOR_GPU_UTILIZATION"] = utilization
    environment["RECORDBENCH_COMPOSE_PROJECT"] = "recordbench-synthetic-upgrade"
    (root / "compose.env").write_text(installer._env_text(environment, "synthetic current runtime"))
    old_release = Path(installation["release_path"])
    new_release = tmp_path.resolve() / "new-release"
    new_release.mkdir()
    (new_release / "compose.yaml").write_text("services: {}\n")
    events = []
    state = {"stopped": False}
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    def probe(command):
        if command[0] == "nvidia-smi":
            events.append("probe-stopped" if state["stopped"] else "probe-live")
            if state["stopped"] and after_free is None:
                raise OSError("synthetic GPU probe failed")
            free = after_free if state["stopped"] else 8000
            return subprocess.CompletedProcess(command, 0, f"0, Synthetic GPU, 49152, {free}, 8.9", "")
        return subprocess.CompletedProcess(command, 0, '{"nvidia": {}}', "")
    def run(console, command, **kwargs):
        verb = next((value for value in ("build", "config", "stop", "up") if value in command), "other")
        release = Path(command[command.index("-f") + 1]).parent if "-f" in command else None
        events.append(f"{verb}-{'old' if release == old_release else 'new'}")
        assert "down" not in command and "--volumes" not in command
        if verb == "stop":
            assert command[command.index("--env-file") + 1] == str(root / "compose.env")
            assert installer._dotenv(root / "compose.env")["RECORDBENCH_COMPOSE_PROJECT"] == "recordbench-synthetic-upgrade"
            assert release == old_release
            if not kwargs.get("dry_run"):
                state["stopped"] = True
        if verb == fail_command:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0, "", "")
    def stage(*a, **k):
        events.append("stage")
        return "synthetic-new", new_release
    monkeypatch.setattr(installer, "_probe", probe)
    monkeypatch.setattr(installer, "_run", run)
    monkeypatch.setattr(installer, "_stage_release", stage)
    monkeypatch.setattr(installer, "_wait_health", lambda *a, **k: events.append("health"))
    monkeypatch.setattr(installer, "_seal_provisioning", lambda *a, **k: events.append("seal"))
    args = installer._parser().parse_args(["update", "--root", str(root), "--non-interactive", "--no-backup", *(["--dry-run"] if dry_run else [])])
    return root, args, events, before


def test_live_gpu_update_checks_freed_capacity_after_own_runtime_stops(tmp_path, ready_host, monkeypatch):
    root, args, events, _before = synthetic_live_update(tmp_path, monkeypatch)
    installer._update(installer.Console(color=False, quiet=True), args, root)
    assert events.index("probe-live") < events.index("build-new")
    assert events.index("build-new") < events.index("config-new") < events.index("stop-old")
    assert events.index("stop-old") < events.index("probe-stopped") < events.index("up-new")
    assert json.loads((root / "installation.json").read_text())["release_id"] == "synthetic-new"

@pytest.mark.parametrize("after_free,utilization", [(1000, "0.72"), (35000, "0.72"), (43000, "0.90"), (None, "0.72")])
def test_live_update_preserves_competing_usage_and_rolls_back(tmp_path, ready_host, monkeypatch, after_free, utilization):
    root, args, events, before = synthetic_live_update(tmp_path, monkeypatch, after_free=after_free, utilization=utilization)
    args.generator_gpus = "1"
    args.review_model_profile = "portable"
    with pytest.raises(RuntimeError, match="update failed and rollback was attempted"):
        installer._update(installer.Console(color=False, quiet=True), args, root)
    assert events.index("stop-old") < events.index("probe-stopped") < events.index("up-old")
    assert "up-new" not in events and events[-1] == "health"
    assert args.generator_gpus == "0" and args.review_model_profile == "quality"
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("failed", ["build", "config", "stop"])
def test_update_failure_keeps_or_restores_old_node(tmp_path, ready_host, monkeypatch, failed):
    root, args, events, before = synthetic_live_update(tmp_path, monkeypatch, fail_command=failed)
    with pytest.raises(RuntimeError, match="update failed and rollback was attempted"):
        installer._update(installer.Console(color=False, quiet=True), args, root)
    assert "up-new" not in events and "up-old" in events
    if failed != "stop":
        assert "stop-old" not in events
    assert "probe-stopped" not in events
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_live_gpu_update_dry_run_defers_post_stop_probe(tmp_path, ready_host, monkeypatch, capsys):
    root, args, events, before = synthetic_live_update(tmp_path, monkeypatch, dry_run=True)
    installer._update(installer.Console(color=False), args, root)
    output = capsys.readouterr().out
    assert "actual free-memory admission is deferred" in output
    assert events.count("probe-live") == 1 and "probe-stopped" not in events
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_deferred_update_check_preserves_real_inventory_and_strict_default(tmp_path, ready_host, monkeypatch):
    root, args, events, _before = synthetic_live_update(tmp_path, monkeypatch)
    installation, _release = installer._installed_release(root)
    installer._restore_model_options(args, installation, installer._dotenv(root / "compose.env"), {})
    strict = installer._collect_preflight("review", model_args=args, needs_model_staging=False)
    assert not strict.ready and checks_by_name(strict)["gpu"].state == "fail"
    deferred = installer._collect_preflight("review", model_args=args, needs_model_staging=False, defer_gpu_free_check=True)
    assert deferred.ready and deferred.devices[0].free_mib == 8000
    assert "deferred" in checks_by_name(deferred)["gpu"].observed
    assert events == ["probe-live", "probe-live"]


@pytest.mark.parametrize("relative", ["matter-storage", "custom-sources", "custom-sources/nested"])
def test_safe_nested_source_storage_remains_allowed(tmp_path, ready_host, relative):
    node = tmp_path.resolve() / "node"
    args = preflight_args(tmp_path, "--root", str(node), "--storage-root", str(node / relative))
    assert installer._collect_preflight("none", args).ready
    assert not node.exists()


@pytest.mark.parametrize("selection", ["same", "parent"])
def test_source_storage_cannot_equal_or_contain_node(tmp_path, ready_host, monkeypatch, selection):
    node = tmp_path.resolve() / "node"
    storage = node if selection == "same" else node.parent
    args = preflight_args(tmp_path, "--root", str(node), "--storage-root", str(storage))
    result = installer._collect_preflight("none", args)
    assert not result.ready and checks_by_name(result)["storage-separation"].state == "fail"
    monkeypatch.setattr(installer, "_prepare_directories", lambda *a, **k: pytest.fail("overlap reached writes"))
    monkeypatch.setattr(sys, "argv", ["install", "--root", str(node), "--storage-root", str(storage), "--models", "none", "--non-interactive", "--password-stdin"])
    assert installer.main() == 1
    assert not node.exists()


@pytest.mark.parametrize("auth,size,expected", [("oidc", 16, True), ("oidc", 4096, True), ("oidc", 4097, False), ("kerberos", 1, True), ("kerberos", 4097, True), ("kerberos", 1024 * 1024, True), ("kerberos", 1024 * 1024 + 1, False)])
def test_provider_metadata_limits_keep_larger_keytabs(tmp_path, ready_host, monkeypatch, auth, size, expected):
    source = tmp_path / "synthetic-credential"
    source.write_bytes(b"x" * size)
    monkeypatch.setattr(Path, "read_bytes", lambda *a, **k: pytest.fail("read secret contents"))
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: pytest.fail("read secret contents"))
    option = "--oidc-client-secret-file" if auth == "oidc" else "--kerberos-keytab"
    args = preflight_args(tmp_path, "--auth", auth, "--dry-run", option, str(source))
    result = installer._collect_preflight("none", args)
    assert result.ready is expected
    assert not args.root.exists()

@pytest.mark.parametrize("state", ["failed", "deferred"])
def test_gpu_update_requires_successful_backup_before_stopping(tmp_path, ready_host, monkeypatch, state):
    root, args, events, _before = synthetic_live_update(tmp_path, monkeypatch)
    (root / "config" / "backup.json").write_text("{}")
    (root / "state").mkdir()
    (root / "state" / "backup-status.json").write_text(json.dumps({"state": state}))
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(RuntimeError, match="newly succeeded backup"):
        installer._update(installer.Console(color=False, quiet=True), args, root)
    assert not any(event.startswith(("stop-", "up-", "build-")) for event in events)
    assert "stage" not in events
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_failed_post_stop_admission_reports_failed_rollback(tmp_path, ready_host, monkeypatch):
    root, args, events, before = synthetic_live_update(tmp_path, monkeypatch, after_free=1000, fail_command="up")
    with pytest.raises(RuntimeError, match="rollback also failed"):
        installer._update(installer.Console(color=False, quiet=True), args, root)
    assert "up-new" not in events and events[-1] == "up-old"
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before

@pytest.mark.parametrize("size", [1, 15])
def test_undersized_oidc_secret_blocks_before_writes_without_reading(tmp_path, ready_host, monkeypatch, size):
    source = tmp_path / "synthetic-small-secret"
    source.write_bytes(b"x" * size)
    flags = ["--auth", "oidc", "--oidc-client-secret-file", str(source), "--non-interactive"]
    args = preflight_args(tmp_path, *flags)
    monkeypatch.setattr(Path, "read_bytes", lambda *a, **k: pytest.fail("read credential contents"))
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: pytest.fail("read credential contents"))
    result = installer._collect_preflight("none", args)
    assert not result.ready and checks_by_name(result)["oidc-secret-input"].state == "fail"
    monkeypatch.setattr(installer, "_prepare_directories", lambda *a, **k: pytest.fail("small secret reached writes"))
    monkeypatch.setattr(sys, "argv", ["install", "--root", str(args.root), "--models", "none", *flags])
    assert installer.main() == 1
    assert not args.root.exists() and source.stat().st_size == size


@pytest.mark.parametrize("field", ["--tls-cert", "--tls-key"])
@pytest.mark.parametrize("control", ["\n", "\r", "\t", "\x7f"])
def test_existing_tls_control_path_blocks_before_writes(tmp_path, ready_host, monkeypatch, field, control):
    cert, key = tmp_path / "synthetic.crt", tmp_path / "synthetic.key"
    malformed = tmp_path / ("synthetic" + control + "tls")
    cert.write_text("synthetic certificate")
    key.write_text("synthetic key")
    malformed.write_text("synthetic supplied TLS material")
    flags = ["--tls-cert", str(cert), "--tls-key", str(key), field, str(malformed), "--non-interactive", "--password-stdin"]
    args = preflight_args(tmp_path, *flags)
    result = installer._collect_preflight("none", args)
    assert not result.ready and checks_by_name(result)["tls"].state == "fail"
    monkeypatch.setattr(installer, "_prepare_directories", lambda *a, **k: pytest.fail("invalid TLS path reached writes"))
    monkeypatch.setattr(sys, "argv", ["install", "--root", str(args.root), "--models", "none", *flags])
    assert installer.main() == 1
    assert not args.root.exists()

@pytest.mark.parametrize("field", ["--tls-cert", "--tls-key"])
def test_tls_nul_path_rejected_before_file_metadata(tmp_path, ready_host, monkeypatch, field):
    cert, key = tmp_path / "synthetic.crt", tmp_path / "synthetic.key"
    cert.write_text("synthetic certificate")
    key.write_text("synthetic key")
    malformed = tmp_path / "synthetic\x00tls"
    args = preflight_args(tmp_path, "--tls-cert", str(cert), "--tls-key", str(key), field, str(malformed))
    original = Path.is_file
    def checked(path):
        assert "\x00" not in str(path), "invalid TLS path reached a file operation"
        return original(path)
    monkeypatch.setattr(Path, "is_file", checked)
    result = installer._collect_preflight("none", args)
    assert not result.ready and checks_by_name(result)["tls"].state == "fail"
    assert not args.root.exists()
