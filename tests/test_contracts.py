import ast
import importlib
import os
import subprocess
import sys
from pathlib import Path

import jsonschema
import yaml
from dcc_mcp_core import validate_skill

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "src/dcc_mcp_slicer/skills/slicer-scene"


def test_no_host_import_at_discovery():
    code = (
        "import dcc_mcp_slicer, dcc_mcp_slicer.server; import sys; assert not {'slicer','qt','vtk'} & set(sys.modules)"
    )
    keys = (
        "PATH",
        "SystemRoot",
        "WINDIR",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "APPDATA",
        "LOCALAPPDATA",
        "TEMP",
        "TMP",
        "PATHEXT",
        "COMSPEC",
        "DCC_MCP_REGISTRY_DIR",
        "DCC_MCP_DISABLE_DEFAULT_SKILL_PATHS",
        "DCC_MCP_DISABLE_FILE_LOGGING",
        "DCC_MCP_DISABLE_TELEMETRY",
        "DCC_MCP_DISABLE_JOB_PERSISTENCE",
        "DCC_MCP_CHECKPOINT_IN_MEMORY",
    )
    environment = {key: os.environ[key] for key in keys if key in os.environ}
    environment["PYTHONPATH"] = str(ROOT / "src")
    subprocess.run([sys.executable, "-c", code], check=True, env=environment)


def test_core_skill_validation():
    report = validate_skill(str(SKILL))
    assert not report.issues, [(issue.severity, issue.message) for issue in report.issues]


def test_declared_tools_are_closed_typed_and_main_affinity():
    tools = yaml.safe_load((SKILL / "tools.yaml").read_text())["tools"]
    assert len(tools) >= 8
    for tool in tools:
        assert tool["input_schema"]["additionalProperties"] is False
        jsonschema.Draft202012Validator.check_schema(tool["input_schema"])
        assert all(
            isinstance(tool["annotations"][name], bool)
            for name in ("read_only_hint", "destructive_hint", "idempotent_hint", "open_world_hint")
        )
        assert tool["affinity"] == ("any" if tool["name"] == "capabilities" else "main")
        tree = ast.parse((SKILL / tool["source_file"]).read_text())
        assert any(isinstance(node, ast.FunctionDef) and node.name == "main" for node in tree.body)
        if tool["name"] in {"save_scene", "reopen_scene", "export_node"}:
            assert tool["execution"] == "async"


def test_schema_rejects_unknown_arguments_and_oversized_volume():
    tools = yaml.safe_load((SKILL / "tools.yaml").read_text())["tools"]
    schema = next(tool for tool in tools if tool["name"] == "create_volume")["input_schema"]
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors({"size": 129}))
    assert list(validator.iter_errors({"script": "anything"}))
    assert not list(validator.iter_errors({"size": 32}))


def test_version():
    assert importlib.import_module("dcc_mcp_slicer").__version__ == "0.1.0"
