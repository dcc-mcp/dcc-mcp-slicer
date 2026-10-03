import pytest


@pytest.fixture(autouse=True)
def isolated_core(monkeypatch, tmp_path):
    monkeypatch.setenv("DCC_MCP_DISABLE_DEFAULT_SKILL_PATHS", "1")
    monkeypatch.setenv("DCC_MCP_REGISTRY_DIR", str(tmp_path / "registry"))
    monkeypatch.setenv("DCC_MCP_CHECKPOINT_IN_MEMORY", "1")
    monkeypatch.setenv("DCC_MCP_DISABLE_FILE_LOGGING", "1")
    monkeypatch.setenv("DCC_MCP_DISABLE_TELEMETRY", "1")
    monkeypatch.setenv("DCC_MCP_DISABLE_JOB_PERSISTENCE", "1")
    monkeypatch.setenv("DCC_MCP_SLICER_WORKSPACE", str(tmp_path))
