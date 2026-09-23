"""Phase 4 loopback composition server for webhook, health, and Remote MCP."""

import argparse
import json
import logging
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grokbuddy.domain.model import HubError  # noqa: E402
from grokbuddy.infrastructure.runtime import LocalRuntime  # noqa: E402
from grokbuddy.infrastructure.reviewer_registry import ReviewerRegistry  # noqa: E402
from grokbuddy.interfaces.composite import create_composite_application  # noqa: E402
from grokbuddy.interfaces.grok_reviewer import GrokReviewerApplication  # noqa: E402
from grokbuddy.adapters.grok_bot import GrokBotReviewerAdapter  # noqa: E402
from grokbuddy.adapters.github import GitHubHttpCommentTransport  # noqa: E402
from grokbuddy.adapters.reviewer_wake import ReviewerWakeHttpTransport  # noqa: E402
from grokbuddy.infrastructure.supervisor_service import SupervisorService  # noqa: E402


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
        help="Additional public hostname allowed by MCP DNS-rebinding protection",
    )
    parser.add_argument(
        "--public-base-url",
        default=os.environ.get("PUBLIC_BASE"),
        help="Stable HTTPS public origin; defaults to PUBLIC_BASE",
    )
    parser.add_argument("--actor", default="builder")
    parser.add_argument("--grok-reviewer-actor", help="Registered Reviewer B actor; enables dedicated ingress")
    parser.add_argument(
        "--reviewer-registry",
        help="Strict non-secret Reviewer registry; formal production selection source",
    )
    parser.add_argument("--grok-public-base-url", help="HTTPS origin for Reviewer request pointers")
    parser.add_argument("--grok-token-env", default="GROKBUDDY_GROK_REVIEWER_TOKEN")
    parser.add_argument("--github-comment-token-env", default="GITHUB_COMMENT_TOKEN")
    parser.add_argument(
        "--reviewer-wake-webhook-url-env",
        default="",
        help="Process environment variable containing the optional wake URL",
    )
    parser.add_argument(
        "--reviewer-wake-webhook-key-env",
        default="",
        help="Process environment variable containing the optional wake sender key",
    )
    parser.add_argument(
        "--reviewer-wake-max-attempts",
        type=int,
        default=3,
        help="Fast transient-failure retry window before capped recovery backoff (1-5)",
    )
    parser.add_argument(
        "--supervisor-interval-seconds",
        type=float,
        default=5,
        help="Persistent worker scan interval (0, 5] seconds",
    )
    parser.add_argument(
        "--disable-supervisor",
        action="store_true",
        help="Disable the production Supervisor only for explicit test/debug runs",
    )
    return parser


def _public_configuration(args):
    public_hosts = list(args.public_host)
    public_base_url = args.public_base_url
    if public_base_url:
        parsed = urlsplit(public_base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise HubError("PUBLIC_BASE must be an HTTPS origin without path, query, or credentials")
        public_base_url = f"https://{parsed.hostname}"
        if parsed.hostname not in public_hosts:
            public_hosts.append(parsed.hostname)
    if args.grok_public_base_url:
        legacy_base = args.grok_public_base_url.rstrip("/")
        if public_base_url and legacy_base != public_base_url:
            raise HubError("Grok public base URL conflicts with PUBLIC_BASE")
        public_base_url = legacy_base
    return public_hosts, public_base_url


def _binding_policy_without_fabrication(_task):
    """Keep the route worker scheduled without inventing PR metadata."""
    return None


def _reviewer_configuration(args):
    if args.reviewer_registry and args.grok_reviewer_actor:
        raise HubError("Reviewer registry and explicit Reviewer actor are mutually exclusive")
    if not args.reviewer_registry:
        return None, args.grok_reviewer_actor
    registry = ReviewerRegistry.load(args.reviewer_registry)
    return registry, registry.active_reviewer_actor_id


def _supervisor_logger():
    logger = logging.getLogger('grokbuddy.supervisor')
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s %(name)s %(message)s'))
        logger.addHandler(handler)
    return logger


def _reviewer_wake_transport(args):
    """Resolve optional wake secrets without logging names or values."""
    url_env = args.reviewer_wake_webhook_url_env
    key_env = args.reviewer_wake_webhook_key_env
    if bool(url_env) != bool(key_env):
        raise HubError("Reviewer wake URL and key environment names must be configured together")
    if not url_env:
        return None
    env_name = re.compile(r"[A-Z][A-Z0-9_]{0,79}\Z")
    if (not env_name.fullmatch(url_env) or not env_name.fullmatch(key_env)
            or url_env == key_env):
        raise HubError("Reviewer wake environment names are invalid")
    reserved = {
        args.webhook_secret_env, args.mcp_token_env, args.grok_token_env,
        args.github_comment_token_env, 'PUBLIC_BASE',
    }
    if url_env in reserved or key_env in reserved:
        raise HubError("Reviewer wake environment names must be independent")
    webhook_url = os.environ.get(url_env)
    sender_key = os.environ.get(key_env)
    if not webhook_url or not sender_key:
        raise HubError("Reviewer wake protected configuration is incomplete")
    return ReviewerWakeHttpTransport(webhook_url, sender_key)


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
        public_hosts, public_base_url = _public_configuration(args)
        reviewer_registry, grok_reviewer_actor = _reviewer_configuration(args)
        default_reviewer = grok_reviewer_actor or 'mock-reviewer'
        runtime = LocalRuntime(
            args.runtime_dir,
            args.contracts_dir,
            default_reviewer_actor_id=default_reviewer,
        )
        if reviewer_registry is not None:
            if (reviewer_registry.active.credential_ref
                    != 'GrokBuddy/GROKBUDDY_GROK_REVIEWER_TOKEN'):
                raise HubError(
                    "Active Reviewer credentialRef is not wired by this production launcher")
            reviewer_registry.register_with(runtime)
        grok_app = None
        supervisor_service = None
        if grok_reviewer_actor:
            reviewer_token = os.environ.get(args.grok_token_env)
            if not reviewer_token or not public_base_url:
                raise HubError("Grok Reviewer token and public HTTPS origin are required")
            if reviewer_token in (mcp_token, webhook_secret):
                raise HubError("Grok Reviewer token must be independent of existing endpoint secrets")
            with runtime.db.transaction() as repo:
                reviewer = repo.get('actors', grok_reviewer_actor)
            if reviewer['role'] != 'REVIEWER' or reviewer['reviewer_type'] != 'grok_bot':
                raise HubError("Configured Grok Reviewer actor is invalid")
            if args.disable_supervisor:
                adapter = GrokBotReviewerAdapter(
                    runtime.db, None, runtime.clock, reviewer_actor_id=reviewer['id'],
                    agent_id=reviewer['agent_id'], server_id=reviewer['server_id'],
                    public_base_url=public_base_url)
                grok_app = GrokReviewerApplication(runtime, adapter, reviewer_token)
            else:
                comment_token = os.environ.get(args.github_comment_token_env)
                if not comment_token:
                    raise HubError('GitHub Comment token is required for production Supervisor')
                if not 1 <= args.reviewer_wake_max_attempts <= 5:
                    raise HubError('Reviewer wake max attempts must be between 1 and 5')
                wake_transport = _reviewer_wake_transport(args)
                if (wake_transport is not None
                        and os.environ.get(args.reviewer_wake_webhook_key_env) in (
                            mcp_token, webhook_secret, reviewer_token, comment_token)):
                    raise HubError('Reviewer wake sender key must be independent')
                transport = GitHubHttpCommentTransport(comment_token)
                intake = runtime.grok_intake(grok_reviewer_actor)
                reviewer_wake = (
                    runtime.grok_reviewer_wake(
                        grok_reviewer_actor, wake_transport,
                        max_attempts=args.reviewer_wake_max_attempts)
                    if wake_transport is not None else None
                )
                dispatcher = runtime.grok_dispatcher(
                    transport, grok_reviewer_actor, public_base_url,
                    intake=intake)
                supervisor = runtime.supervisor(
                    projection_transport=transport,
                    binding_policy=_binding_policy_without_fabrication,
                    dispatcher=dispatcher,
                    intake=intake,
                    intake_source='grok-reviewer-http',
                    reviewer_wake=reviewer_wake,
                )
                supervisor_service = SupervisorService(
                    supervisor,
                    interval_seconds=args.supervisor_interval_seconds,
                    logger=_supervisor_logger(),
                )
                grok_app = GrokReviewerApplication(
                    runtime, dispatcher.adapter, reviewer_token, intake=intake)
        elif not args.disable_supervisor:
            raise HubError('Production Supervisor requires a configured Grok Reviewer actor')
        application = create_composite_application(
            runtime,
            webhook_secret,
            mcp_token,
            public_hosts=public_hosts,
            actor_id=args.actor,
            grok_reviewer_app=grok_app,
            supervisor_readiness_check=(
                supervisor_service.is_ready if supervisor_service is not None else None),
        )
        application.supervisor_service = supervisor_service
        import uvicorn

        if supervisor_service is not None:
            supervisor_service.start()
        try:
            uvicorn.run(
                application,
                host=args.host,
                port=args.port,
                log_level="warning",
                access_log=False,
            )
        finally:
            if supervisor_service is not None:
                supervisor_service.stop()
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
