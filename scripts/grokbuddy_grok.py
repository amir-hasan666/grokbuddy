"""Explicit Grok Bot setup and one-shot workers. Never runs the Mock queue."""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from grokbuddy.adapters.github import GitHubHttpCommentTransport  # noqa: E402
from grokbuddy.domain.model import HubError  # noqa: E402
from grokbuddy.infrastructure.runtime import LocalRuntime  # noqa: E402


def _parser():
    parser = argparse.ArgumentParser(description='Explicit Grok Reviewer Application operations')
    parser.add_argument('--runtime-dir', required=True)
    parser.add_argument('--contracts-dir', default=str(ROOT / 'docs' / 'contracts'))
    commands = parser.add_subparsers(dest='command', required=True)
    register = commands.add_parser('register-reviewer')
    register.add_argument('--actor-id', required=True)
    register.add_argument('--name', required=True)
    register.add_argument('--agent-id', required=True)
    register.add_argument('--server-id', required=True)
    route = commands.add_parser('route-task')
    route.add_argument('--task-id', required=True)
    route.add_argument('--reviewer-actor-id', required=True)
    route.add_argument('--expected-version', type=int, required=True)
    route.add_argument('--key', required=True)
    dispatch = commands.add_parser('dispatch-once')
    dispatch.add_argument('--reviewer-actor-id', required=True)
    dispatch.add_argument('--public-base-url', required=True)
    dispatch.add_argument('--comment-token-env', default='GITHUB_COMMENT_TOKEN')
    retry = commands.add_parser('retry-final', help='Human resume and new Reviewer B RR via Application')
    retry.add_argument('--task-id', required=True)
    retry.add_argument('--old-request-id', required=True)
    retry.add_argument('--expected-version', type=int, required=True)
    retry.add_argument('--new-limit', type=int, required=True)
    retry.add_argument('--new-deadline-utc', required=True,
                       help='Future ISO 8601 UTC timestamp, e.g. 2026-09-21T06:00:00Z')
    retry.add_argument('--reason', required=True)
    retry.add_argument('--key', required=True)
    commands.add_parser('event-once')
    commands.add_parser('timeout-once')
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        runtime = LocalRuntime(args.runtime_dir, args.contracts_dir)
        if args.command == 'register-reviewer':
            row = runtime.hub.register_reviewer('system', args.actor_id, args.name,
                                                args.agent_id, args.server_id)
            result = {'actor_id': row['id'], 'provider_id': row['provider_id'],
                      'reviewer_type': row['reviewer_type']}
        elif args.command == 'route-task':
            row = runtime.hub.route_future_reviews('builder', args.task_id,
                                                    args.reviewer_actor_id,
                                                    args.expected_version, args.key)
            result = {'route_id': row['id'], 'task_id': row['task_id'],
                      'reviewer_actor_id': row['reviewer_actor_id'],
                      'applies_to': row['applies_to']}
        elif args.command == 'dispatch-once':
            token = os.environ.get(args.comment_token_env)
            if not token:
                raise HubError('GitHub Comment token is required for Grok request dispatch')
            transport = GitHubHttpCommentTransport(token)
            dispatcher = runtime.grok_dispatcher(transport, args.reviewer_actor_id,
                                                 args.public_base_url)
            result = {'dispatch': dispatcher.dispatch_one()}
        elif args.command == 'retry-final':
            try:
                deadline = datetime.fromisoformat(args.new_deadline_utc.replace('Z', '+00:00'))
                if deadline.tzinfo is None or deadline.utcoffset() != timezone.utc.utcoffset(deadline):
                    raise ValueError('UTC offset is required')
                micros = int(deadline.timestamp() * 1_000_000)
            except (ValueError, OverflowError) as exc:
                raise HubError('new-deadline-utc must be a future UTC ISO 8601 timestamp') from exc
            result = runtime.hub.retry_final_with_grok(
                'human', 'builder', args.task_id, args.old_request_id,
                args.new_limit, micros, args.reason, args.expected_version, args.key)
        elif args.command == 'event-once':
            result = {'event': runtime.events.handle_one()}
        else:
            result = {'timeouts': runtime.timeouts.sweep()}
        print(json.dumps({'ok': True, 'result': result}, ensure_ascii=False, sort_keys=True))
        return 0
    except HubError as exc:
        print(json.dumps({'ok': False, 'error': {'code': exc.code, 'message': str(exc)}},
                         ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
