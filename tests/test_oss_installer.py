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
