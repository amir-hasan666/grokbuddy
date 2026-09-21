"""Phase 3/3.5 GitHub Webhook and explicit Comment-projection runner."""

import argparse
import json
import os
from pathlib import Path
import sys
from wsgiref.simple_server import make_server

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grokbuddy.adapters.github import FileGitHubCommentTransport, GitHubHttpCommentTransport
from grokbuddy.domain.model import HubError
from grokbuddy.infrastructure.runtime import LocalRuntime
from grokbuddy.interfaces.github import GitHubWebhookApplication


def _parser():
    parser = argparse.ArgumentParser(description="GrokBuddy Phase 3 local GitHub adapter")
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--contracts-dir", default=str(ROOT / "docs" / "contracts"))
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="Serve the signed Webhook endpoint on loopback")
    serve.add_argument("--secret-env", default="GITHUB_WEBHOOK_SECRET")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)

    bind = commands.add_parser("bind-pr", help="Bind one Hub Task to one PR without calling GitHub")
    bind.add_argument("--repository-id", type=int, required=True)
    bind.add_argument("--repository-full-name", required=True)
    bind.add_argument("--pull-request-number", type=int, required=True)
    bind.add_argument("--task-id", required=True)
    bind.add_argument("--builder-actor", default="builder")
    bind.add_argument("--reviewer-actor", default="mock-reviewer")
    bind.add_argument("--hub-pointer-base", default="hub://local")

    project = commands.add_parser("project-once", help="Project one completed result to a local Comment mock")
    project.add_argument("--review-request-id", required=True)
    project.add_argument("--comments-file", required=True)

    project_http = commands.add_parser(
        "project-github-once", help="Explicitly project one completed result to GitHub REST")
    project_http.add_argument("--review-request-id", required=True)
    project_http.add_argument("--token-env", default="GITHUB_COMMENT_TOKEN")
    project_http.add_argument("--api-base-url", default="https://api.github.com")
    project_http.add_argument("--timeout", type=float, default=15)
    project_http.add_argument("--max-comment-pages", type=int, default=10)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        runtime = LocalRuntime(args.runtime_dir, args.contracts_dir)
        if args.command == "serve":
            if args.host not in ("127.0.0.1", "localhost", "::1"):
                raise HubError("The Phase 3 local webhook may bind only to loopback")
            secret = os.environ.get(args.secret_env)
            if not secret:
                raise HubError(f"Webhook secret environment variable {args.secret_env} is not set")
            app = GitHubWebhookApplication(runtime, secret)
            with make_server(args.host, args.port, app) as server:
                server.serve_forever()
            return 0
        if args.command == "bind-pr":
            result = runtime.github_bindings.bind_pull_request(
                repository_id=args.repository_id,
                repository_full_name=args.repository_full_name,
                pull_request_number=args.pull_request_number,
                task_id=args.task_id,
                builder_actor_id=args.builder_actor,
                reviewer_actor_id=args.reviewer_actor,
                hub_pointer_base=args.hub_pointer_base,
            )
        elif args.command == "project-once":
            runtime.github_projections.enqueue_final_review(args.review_request_id)
            operation = runtime.github_projections.project_one(
                FileGitHubCommentTransport(args.comments_file))
            result = {"operation": operation, "comments_file": str(Path(args.comments_file).resolve())}
        else:
            token = os.environ.get(args.token_env)
            if not token:
                raise HubError(f"GitHub token environment variable {args.token_env} is not set")
            runtime.github_projections.enqueue_final_review(args.review_request_id)
            operation = runtime.github_projections.project_one(GitHubHttpCommentTransport(
                token, api_base_url=args.api_base_url, timeout=args.timeout,
                max_comment_pages=args.max_comment_pages))
            result = {"operation": operation, "transport": "github-http"}
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, sort_keys=True))
        return 0
    except HubError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": str(exc)}},
                         ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
