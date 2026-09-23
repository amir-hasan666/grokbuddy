"""Validate formal Reviewer Registry configuration without reading secrets."""

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grokbuddy.domain.model import HubError  # noqa: E402
from grokbuddy.infrastructure.reviewer_registry import (  # noqa: E402
    load_service_reviewer_registry,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--service-config",
        default=str(ROOT / "config" / "grokbuddy.service.json"),
    )
    args = parser.parse_args(argv)
    try:
        registry, registry_path = load_service_reviewer_registry(args.service_config)
        active = registry.active
        print(json.dumps({
            "active_reviewer_actor_id": active.actor_id,
            "credential_ref": active.credential_ref,
            "display_name": active.display_name,
            "ok": True,
            "registry_path": str(registry_path),
            "reviewer_count": len(registry.reviewers),
            "reload": "RESTART_REQUIRED",
        }, ensure_ascii=False, sort_keys=True))
        return 0
    except HubError as exc:
        print(json.dumps({
            "error": {"code": exc.code, "message": str(exc)},
            "ok": False,
        }, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
