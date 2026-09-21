"""Dedicated WorkBuddy trigger ingress with no general Builder tool surface."""

import argparse
import hashlib
import json
from pathlib import Path
import threading
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from grokbuddy.application.trigger import issue_trigger_evidence
from grokbuddy.application.common import digest
from grokbuddy.domain.model import HubError
from grokbuddy.infrastructure.runtime import LocalRuntime
from .gateway import ClientGateway
from .mcp import IDEMPOTENT_WRITE, _call


INGRESS_ACTOR_ID = 'workbuddy-ingress'
INGRESS_TOOL_NAMES = ('create_triggered_task',)


def _default_contracts():
    return Path(__file__).resolve().parents[3] / 'docs' / 'contracts'


def _derived_id(kind, conversation_id, idempotency_key):
    identifier_digest = hashlib.sha256(
        f'{kind}\0{conversation_id}\0{idempotency_key}'.encode('utf-8')).hexdigest()
    return f'workbuddy-{kind}-{identifier_digest}'


def _existing_evidence(runtime, idempotency_key, conversation_id, segments,
                       profile, profile_version):
    """Rebuild the exact first input so command replay survives MCP restarts."""
    receipt_id = digest([INGRESS_ACTOR_ID, 'create_task', idempotency_key])
    with runtime.db.transaction() as repo:
        receipts = repo.find('command_receipts', id=receipt_id)
    if not receipts:
        return None
    task = receipts[0]['response']
    frozen = task.get('trigger_evidence')
    if (task.get('profile') != profile or task.get('profile_version') != profile_version
            or not isinstance(frozen, dict)):
        return None
    source = runtime.hub.get_artifact(frozen['source_artifact_id'])
    source_bytes = runtime.store.read(
        source['storage_pointer'], source['sha256'], source['size_bytes'])
    message = json.loads(source_bytes.decode('utf-8'))
    if (message.get('conversation_id') != conversation_id
            or message.get('segments') != segments):
        return None
    body = ''.join(segment['text'] for segment in segments)
    return body, {
        'message': message,
        'signature': frozen['signature'],
        'body_sha256': frozen['body_sha256'],
        'phrase': frozen['phrase'],
        'start_byte': frozen['start_byte'],
        'end_byte': frozen['end_byte'],
    }


def create_ingress_mcp_server(runtime):
    """Bind the restricted WorkBuddy connector to the ingress principal.

    The companion Skill passes WorkBuddy's runtime-expanded
    ``CODEBUDDY_SESSION_ID``. Stable message/turn IDs are derived from that
    native session ID plus the per-message idempotency key. The server never
    accepts an actor or signature.
    """

    gateway = ClientGateway(runtime, INGRESS_ACTOR_ID)
    issuance_lock = threading.Lock()
    server = MCPServer(
        name='grokbuddy-ingress',
        title='GrokBuddy WorkBuddy Trigger Ingress',
        description='Restricted WorkBuddy trigger attestation and Task creation.',
        instructions=(
            'Use only for the current user turn when its top-level natural-language body '
            'contains the exact phrase 启用grokbuddy流程. Never use grokbuddy-hub.create_task '
            'as a fallback.'
        ),
        version='0.1.0',
        log_level='WARNING',
    )

    @server.tool(annotations=IDEMPOTENT_WRITE)
    def create_triggered_task(
        segments: list[dict[str, str]],
        conversation_id: str,
        idempotency_key: str,
        profile: str = 'generic',
        profile_version: str = '1.0',
    ) -> dict[str, Any]:
        """Attest the current user message, then create through the guarded Hub path.

        Preserve the exact current message order. Mark ordinary text as
        ``user_body`` and use ``code_block``, ``quote``, ``pasted_document``,
        ``attachment`` or ``tool_output`` for excluded provenance. Pass the
        runtime-expanded WorkBuddy session ID, never the placeholder literal.
        """
        with issuance_lock:
            if conversation_id in ('${CODEBUDDY_SESSION_ID}', '${CLAUDE_SESSION_ID}'):
                raise ToolError(
                    'VALIDATION_FAILURE: WorkBuddy session placeholder was not expanded')
            existing = _existing_evidence(
                runtime, idempotency_key, conversation_id, segments,
                profile, profile_version)
            if existing is None:
                now = runtime.clock.now()
                message_id = _derived_id('message', conversation_id, idempotency_key)
                message = {
                    'principal_id': INGRESS_ACTOR_ID,
                    'conversation_id': conversation_id,
                    'message_id': message_id,
                    'turn_id': _derived_id('turn', conversation_id, idempotency_key),
                    'message_role': 'user',
                    'issued_at': now,
                    'segments': segments,
                }
                try:
                    description, evidence = issue_trigger_evidence(
                        message, runtime.hub.trigger_source_key, now)
                except HubError as exc:
                    raise ToolError(f'{exc.code}: {exc}') from exc
            else:
                description, evidence = existing
            return _call(gateway, 'create_task', {
                'description': description,
                'idempotency_key': idempotency_key,
                'profile': profile,
                'profile_version': profile_version,
                'trigger_evidence': evidence,
            })

    return server


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='GrokBuddy dedicated WorkBuddy trigger ingress MCP (stdio)')
    parser.add_argument('--runtime-dir', required=True)
    parser.add_argument('--contracts-dir', default=str(_default_contracts()))
    args = parser.parse_args(argv)
    runtime = LocalRuntime(args.runtime_dir, args.contracts_dir)
    create_ingress_mcp_server(runtime).run(transport='stdio')


if __name__ == '__main__':
    main()
