"""Tests for appliance first-run setup (no network / no heavy installs)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from deploy import appliance_setup as setup


def test_detect_device_returns_struct():
    info = setup.detect_device()
    assert isinstance(info.has_cuda, bool)
    assert info.arch in ("x86", "arm")
    assert info.vram_mb >= 0
    if info.has_cuda:
        assert info.gpu_name


def test_write_local_env_gpu(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "LOCAL_ENV_PATH", tmp_path / "local.yaml")
    device = setup.DeviceInfo(has_cuda=True, gpu_name="Test GPU", vram_mb=8188, arch="x86")
    setup.write_local_env(device, lambda *_: None)
    raw = yaml.safe_load(setup.LOCAL_ENV_PATH.read_text(encoding="utf-8"))
    assert raw["name"] == "local"
    assert raw["device"] == "cuda"
    assert raw["vram_ceiling_mb"] == 8188 - 700
    assert raw["max_resident_gpu_models"] == 1


def test_write_local_env_cpu(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "LOCAL_ENV_PATH", tmp_path / "local.yaml")
    device = setup.DeviceInfo(has_cuda=False, gpu_name=None, vram_mb=0, arch="x86")
    setup.write_local_env(device, lambda *_: None)
    raw = yaml.safe_load(setup.LOCAL_ENV_PATH.read_text(encoding="utf-8"))
    assert raw["device"] == "cpu"
    assert raw["vram_ceiling_mb"] == 0
    assert raw["max_resident_gpu_models"] == 0
    assert raw["default_precision"] == "fp32"


def test_env_profile_local_roundtrip(tmp_path, monkeypatch):
    # Write a real local.yaml into the repo config dir via the helper, then load.
    device = setup.detect_device()
    setup.write_local_env(device, lambda *_: None)
    monkeypatch.setenv("SS_ENV", "local")
    from core.env import AppConfig

    cfg = AppConfig.load("local")
    assert cfg.env.name == "local"
    if device.has_cuda:
        assert cfg.env.device.startswith("cuda")
    else:
        assert cfg.env.device == "cpu"


def test_write_and_load_state(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(setup, "STATE_PATH", tmp_path / "setup_state.json")
    device = setup.DeviceInfo(has_cuda=True, gpu_name="GPU", vram_mb=8000, arch="x86")
    setup.write_state(device, ok=True)
    state = setup.load_state()
    assert state is not None
    assert state["ok"] is True
    assert state["device"]["gpu_name"] == "GPU"


def test_asset_paths_are_under_weights():
    assert "whisper-large-v3-vaani-hindi-ct2-int8" in str(setup.VAANI_DIR)
    assert "faster-whisper-large-v3" in str(setup.MULTILINGUAL_DIR)
    assert setup.VAANI_REPO.startswith("bjollans/")
    assert setup.MULTILINGUAL_REPO.startswith("Systran/")


def test_verify_ready_reports_list():
    problems = setup.verify_ready()
    assert isinstance(problems, list)
