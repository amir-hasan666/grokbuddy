"""JSON-file CLI fallback for the Phase 2 client tool surface."""

import argparse
import json
from pathlib import Path
import sys

from grokbuddy.domain.model import HubError
from grokbuddy.infrastructure.runtime import LocalRuntime
from .gateway import ClientGateway, TOOL_NAMES


def _default_contracts():
    return Path(__file__).resolve().parents[3] / "docs" / "contracts"


def _read_payload(path):
    try:
        if path == "-":
            value = json.load(sys.stdin)
        else:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HubError("Unable to read JSON tool input") from exc
    if not isinstance(value, dict):
        raise HubError("Tool input must be a JSON object")
    return value


def _parser():
    parser = argparse.ArgumentParser(description="GrokBuddy local HTTP/CLI fallback")
    parser.add_argument("--runtime-dir", required=True, help="Local Hub data directory")
    parser.add_argument("--contracts-dir", default=str(_default_contracts()))
    parser.add_argument("--actor", default="builder", help="Configured local simulation principal")
    parser.add_argument("command", choices=(*TOOL_NAMES, "worker-once"))
    parser.add_argument("--input", help="UTF-8 JSON file, or - for stdin")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        runtime = LocalRuntime(args.runtime_dir, args.contracts_dir)
        if args.command == "worker-once":
            if args.input:
                raise HubError("worker-once does not accept tool input")
            result = runtime.tick()
        else:
            if not args.input:
                raise HubError("--input is required for client tools")
            result = ClientGateway(runtime, args.actor).invoke(args.command, _read_payload(args.input))
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, sort_keys=True))
        return 0
    except HubError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": str(exc)}},
                         ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
