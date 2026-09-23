"""Repository checkout entry point for the WorkBuddy stdio MCP server."""

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from grokbuddy.interfaces.mcp import main  # noqa: E402
from grokbuddy.infrastructure.reviewer_registry import (  # noqa: E402
    load_service_reviewer_registry,
)


def _argument_value(argv, name):
    try:
        return argv[argv.index(name) + 1]
    except (ValueError, IndexError):
        return None


def _service_reviewer_default(argv):
    """Use service SoT only when this MCP points at the formal runtime directory."""
    runtime_value = _argument_value(argv, '--runtime-dir')
    if runtime_value is None:
        return 'mock-reviewer'
    config = json.loads((ROOT / 'config' / 'grokbuddy.service.json').read_text(
        encoding='utf-8'))
    configured_runtime = (ROOT / config['runtimeDir']).resolve()
    requested_runtime = Path(runtime_value)
    if not requested_runtime.is_absolute():
        requested_runtime = (Path.cwd() / requested_runtime).resolve()
    else:
        requested_runtime = requested_runtime.resolve()
    if requested_runtime != configured_runtime:
        return 'mock-reviewer'
    registry, _ = load_service_reviewer_registry(
        ROOT / 'config' / 'grokbuddy.service.json')
    return registry.active_reviewer_actor_id


if __name__ == "__main__":
    arguments = sys.argv[1:]
    main(arguments, default_reviewer_actor_id=_service_reviewer_default(arguments))
