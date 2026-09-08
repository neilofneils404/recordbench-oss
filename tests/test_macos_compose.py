"""Evaluate the actual merged Compose model using synthetic configuration."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def macos_compose(tmp_path_factory):
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose is required to validate service inheritance")
    version = subprocess.run(
        ["docker", "compose", "version"], capture_output=True, check=False
    )
    if version.returncode:
        pytest.skip("Docker Compose plugin is unavailable")
    root = tmp_path_factory.mktemp("synthetic-macos-compose")
    (root / "recordbench.env").write_text(
        "CASE_INTELLIGENCE_AUTH_MODE=local\nCASE_INTELLIGENCE_GENERATOR_BACKEND=ollama\n"
    )
    (root / "transcription.env").write_text("TRANSCRIPTION_V2_PIPELINE=mock\n")
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("RECORDBENCH_", "COMPOSE_"))
    }
    for name in (
        "CONFIG_ROOT", "MODEL_ROOT", "TRANSCRIPTION_ROOT", "SECRETS_ROOT",
        "RUNTIME_ROOT", "STORAGE_ROOT", "STATE_ROOT",
    ):
        environment[f"RECORDBENCH_{name}"] = str(root)
    environment.update({
        "RECORDBENCH_TLS_CERT": str(root / "synthetic.crt"),
        "RECORDBENCH_TLS_KEY": str(root / "synthetic.key"),
        # A Linux shell configuration must not accidentally publish Mac access.
        "RECORDBENCH_BIND_ADDRESS": "0.0.0.0",
        "RECORDBENCH_RETRIEVAL_DEVICE": "cuda",
    })
    result = subprocess.run(
        ["docker", "compose", "-f", "compose.macos.yaml", "--profile", "*",
         "config", "--format", "json"],
        cwd=ROOT, env=environment, capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def test_mac_topology_never_requests_nvidia_or_imports_generator(macos_compose):
    services = macos_compose["services"]
    assert "generator" not in services
    for service in services.values():
        assert service["platform"] == "linux/arm64"
        assert not service.get("gpus")
        assert service.get("runtime") != "nvidia"
    retrieval = services["retrieval"]
    assert retrieval["build"]["target"] == "retrieval-cpu"
    assert "--warm-models" in retrieval["command"]
    assert retrieval["environment"]["CASE_REVIEW_MODEL_DEVICE"] == "cpu"
    worker = services["transcription-worker"]
    assert worker["build"]["target"] == "worker-cpu"
    assert worker["environment"]["TRANSCRIPTION_V2_DEVICE"] == "cpu"


def test_mac_keeps_parsers_and_models_isolated(macos_compose):
    services = macos_compose["services"]
    assert macos_compose["networks"]["models"]["internal"] is True
    assert macos_compose["networks"]["services"]["internal"] is True
    for name in ("app", "retrieval", "transcription-worker"):
        service = services[name]
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in service["security_opt"]
    assert set(services["clamav"]["networks"]) == {"services"}
    assert set(services["clamav-updater"]["networks"]) == {"updates"}
    assert set(services["retrieval"]["networks"]) == {"models"}
    assert services["transcription-worker"]["network_mode"] == "none"
    cleanup = services["transcription-cleanup-daemon"]
    assert cleanup["network_mode"] == "none"
    assert cleanup["healthcheck"]["disable"] is True
    assert cleanup["restart"] == "unless-stopped"
    assert services["retrieval"]["environment"]["HF_HUB_OFFLINE"] == "1"
    assert services["transcription-worker"]["environment"]["HF_HUB_OFFLINE"] == "1"


def test_only_gateway_is_published_and_mac_generation_is_exactly_allowlisted(macos_compose):
    services = macos_compose["services"]
    for name, service in services.items():
        if name != "gateway":
            assert not service.get("ports"), name
    ports = services["gateway"]["ports"]
    assert len(ports) == 1
    assert ports[0]["host_ip"] == "127.0.0.1"
    assert ports[0]["target"] == 8443
    environment = services["app"]["environment"]
    assert environment["CASE_INTELLIGENCE_GENERATOR_BACKEND"] == "ollama"
    assert environment["CASE_INTELLIGENCE_GENERATOR_URL"] == "http://host.docker.internal:11435"
    assert environment["CASE_INTELLIGENCE_GENERATOR_ALLOWED_HOSTS"] == "host.docker.internal"
    assert "generator" not in services["app"]["depends_on"]
    assert services["app"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert services["app"]["depends_on"]["clamav"]["condition"] == "service_healthy"


def test_mac_cpu_targets_assert_cuda_is_absent():
    dockerfile = (ROOT / "Dockerfile").read_text()
    cpu_target = dockerfile.split("FROM application AS retrieval-cpu", 1)[1].split(
        "FROM application AS retrieval", 1
    )[0]
    assert "torch==2.8.0" in cpu_target
    assert "https://download.pytorch.org/whl/cpu" in cpu_target
    assert "assert torch.version.cuda is None" in cpu_target


def test_mac_stager_uses_writable_model_and_ephemeral_transfer_caches(macos_compose):
    stager = macos_compose["services"]["model-stager"]
    assert stager["read_only"] is True
    assert stager["environment"]["HF_HOME"] == "/models/huggingface"
    assert stager["environment"]["HF_XET_CACHE"] == "/tmp/xet"
    assert any(volume["target"] == "/models" and not volume.get("read_only")
               for volume in stager["volumes"])
    assert any(mount.startswith("/tmp:") for mount in stager["tmpfs"])


def test_mac_transcription_admission_checks_the_same_cpu_runtime_as_the_worker(macos_compose):
    services = macos_compose["services"]
    api = services["transcription-api"]
    worker = services["transcription-worker"]
    assert api["image"] == worker["image"]
    assert api["build"]["target"] == worker["build"]["target"] == "worker-cpu"
    assert api["command"] == ["transcription-v2", "api"]
    assert api["environment"]["TRANSCRIPTION_V2_DEVICE"] == "cpu"
    assert api["healthcheck"]["test"] == [
        "CMD", "curl", "--fail", "--silent", "http://127.0.0.1:8510/health",
    ]
    assert set(api["networks"]) == {"services"}
    assert not api.get("ports")
    for service in (api, worker):
        model_volume = next(volume for volume in service["volumes"] if volume["target"] == "/models")
        assert model_volume["read_only"] is True
    assert api["environment"]["TRANSCRIPTION_V2_MODEL_CACHE"] == worker["environment"]["TRANSCRIPTION_V2_MODEL_CACHE"]
