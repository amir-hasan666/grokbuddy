"""Phase 4 loopback composition server for webhook, health, and Remote MCP."""

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grokbuddy.domain.model import HubError  # noqa: E402
from grokbuddy.infrastructure.runtime import LocalRuntime  # noqa: E402
from grokbuddy.interfaces.composite import create_composite_application  # noqa: E402
from grokbuddy.interfaces.grok_reviewer import GrokReviewerApplication  # noqa: E402
from grokbuddy.adapters.grok_bot import GrokBotReviewerAdapter  # noqa: E402


def _parser():
    parser = argparse.ArgumentParser(
        description="GrokBuddy Phase 4 loopback composite HTTP server"
    )
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--contracts-dir", default=str(ROOT / "docs" / "contracts"))
    parser.add_argument("--webhook-secret-env", default="GITHUB_WEBHOOK_SECRET")
    parser.add_argument("--mcp-token-env", default="GROKBUDDY_MCP_TOKEN")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument(
        "--public-host",
        action="append",
        default=[],
        help="Existing tunnel hostname allowed by MCP DNS-rebinding protection",
    )
    parser.add_argument("--actor", default="builder")
    parser.add_argument("--grok-reviewer-actor", help="Registered Reviewer B actor; enables dedicated ingress")
    parser.add_argument("--grok-public-base-url", help="HTTPS origin for Reviewer request pointers")
    parser.add_argument("--grok-token-env", default="GROKBUDDY_GROK_REVIEWER_TOKEN")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.host not in ("127.0.0.1", "localhost", "::1"):
            raise HubError("The composite server may bind only to loopback")
        webhook_secret = os.environ.get(args.webhook_secret_env)
        if not webhook_secret:
            raise HubError(
                f"Webhook secret environment variable {args.webhook_secret_env} is not set"
            )
        mcp_token = os.environ.get(args.mcp_token_env)
        if not mcp_token:
            raise HubError(
                f"MCP token environment variable {args.mcp_token_env} is not set"
            )
        runtime = LocalRuntime(args.runtime_dir, args.contracts_dir)
        grok_app = None
        if args.grok_reviewer_actor:
            reviewer_token = os.environ.get(args.grok_token_env)
            if not reviewer_token or not args.grok_public_base_url:
                raise HubError("Grok Reviewer token and public HTTPS origin are required")
            if reviewer_token in (mcp_token, webhook_secret):
                raise HubError("Grok Reviewer token must be independent of existing endpoint secrets")
            with runtime.db.transaction() as repo:
                reviewer = repo.get('actors', args.grok_reviewer_actor)
            if reviewer['role'] != 'REVIEWER' or reviewer['reviewer_type'] != 'grok_bot':
                raise HubError("Configured Grok Reviewer actor is invalid")
            adapter = GrokBotReviewerAdapter(
                runtime.db, None, runtime.clock, reviewer_actor_id=reviewer['id'],
                agent_id=reviewer['agent_id'], server_id=reviewer['server_id'],
                public_base_url=args.grok_public_base_url)
            grok_app = GrokReviewerApplication(runtime, adapter, reviewer_token)
        application = create_composite_application(
            runtime,
            webhook_secret,
            mcp_token,
            public_hosts=args.public_host,
            actor_id=args.actor,
            grok_reviewer_app=grok_app,
        )
        import uvicorn

        uvicorn.run(
            application,
            host=args.host,
            port=args.port,
            log_level="warning",
            access_log=False,
        )
        return 0
    except HubError as exc:
        print(
            json.dumps(
                {"ok": False, "error": {"code": exc.code, "message": str(exc)}},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
