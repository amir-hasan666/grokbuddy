"""Dedicated, token-authenticated Grok Reviewer read and event ingress surface."""

import json
import re
import secrets

from grokbuddy.domain.model import HubError, PermissionDenied


_REQUEST = re.compile(r"/reviewer/requests/(RR-[A-Za-z0-9-]+)\Z")
_ARTIFACT = re.compile(r"/reviewer/requests/(RR-[A-Za-z0-9-]+)/artifacts/(ART-[A-Za-z0-9-]+)\Z")
_REQUESTS = '/reviewer/requests'
_MATERIALS = re.compile(r"/reviewer/requests/(RR-[A-Za-z0-9-]+)/materials\Z")
_MATERIALS_CHECK = re.compile(r"/reviewer/requests/(RR-[A-Za-z0-9-]+)/materials/check\Z")
_VALIDATE_RESULT = re.compile(r"/reviewer/requests/(RR-[A-Za-z0-9-]+)/validate-result\Z")
_INGRESS = re.compile(r"/reviewer/ingress/(IN-[A-Za-z0-9-]+)\Z")
_RESULT_SCHEMA = '/reviewer/contracts/review-result.schema.json'
_CONTRACTS = '/reviewer/contracts'
MAX_EVENT_BODY = 1024 * 1024


async def _respond(send, status, body, headers=()):
    data = json.dumps(body, ensure_ascii=False, sort_keys=True).encode('utf-8')
    await send({'type': 'http.response.start', 'status': status,
                'headers': [(b'content-type', b'application/json; charset=utf-8'),
                            (b'content-length', str(len(data)).encode('ascii')), *headers]})
    await send({'type': 'http.response.body', 'body': data})


async def _read_body(receive, send, headers):
    lengths = [v for k, v in headers if k.lower() == b'content-length']
    try:
        length = int(lengths[0]) if len(lengths) == 1 else -1
    except ValueError:
        length = -1
    if not 0 <= length <= MAX_EVENT_BODY:
        await _respond(send, 413, {'error': 'invalid_length'})
        return None
    body = bytearray()
    more = True
    while more and len(body) <= length:
        part = await receive()
        if part.get('type') == 'http.disconnect':
            return None
        chunk = part.get('body', b'')
        if len(body) + len(chunk) > length:
            await _respond(send, 413, {'error': 'body_exceeds_declared_length'})
            return None
        body.extend(chunk)
        more = part.get('more_body', False)
    if len(body) != length:
        await _respond(send, 400, {'error': 'body_length_mismatch'})
        return None
    return bytes(body)


class GrokReviewerApplication:
    def __init__(self, runtime, adapter, token, intake=None):
        self.runtime, self.adapter, self.intake = runtime, adapter, intake
        self.replace_tokens(token)

    def replace_tokens(self, tokens):
        """Atomically replace the active token set; at most two support overlap rotation."""
        if isinstance(tokens, str):
            tokens = [tokens]
        if (not isinstance(tokens, (list, tuple)) or not 1 <= len(tokens) <= 2
                or any(not isinstance(token, str) or not token
                       or '\r' in token or '\n' in token for token in tokens)
                or len(set(tokens)) != len(tokens)):
            raise HubError('One or two distinct dedicated Grok Reviewer tokens are required')
        self.expected_tokens = tuple(('Bearer ' + token).encode('utf-8') for token in tokens)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await _respond(send, 404, {'error': 'not_found'})
            return
        headers = scope.get('headers', [])
        auth = [v for k, v in headers if k.lower() == b'authorization']
        authorized = len(auth) == 1
        matches = [secrets.compare_digest(auth[0], expected)
                   for expected in self.expected_tokens] if authorized else []
        if not authorized or not any(matches):
            await _respond(send, 401, {'error': 'unauthorized'}, ((b'www-authenticate', b'Bearer'),))
            return
        path, method = scope.get('path', ''), scope.get('method')
        artifact_match = _ARTIFACT.fullmatch(path)
        request_match = _REQUEST.fullmatch(path)
        materials_match = _MATERIALS.fullmatch(path)
        materials_check_match = _MATERIALS_CHECK.fullmatch(path)
        validate_match = _VALIDATE_RESULT.fullmatch(path)
        ingress_match = _INGRESS.fullmatch(path)
        try:
            if method == 'GET' and path == _RESULT_SCHEMA:
                await _respond(send, 200, self.runtime.contracts.validators['result'].schema)
                return
            if method == 'GET' and path == _CONTRACTS:
                await _respond(send, 200, {'schemas': self.runtime.contracts.bundle()})
                return
            if method == 'GET' and materials_check_match:
                await _respond(send, 200, self.runtime.hub.grok_materials_check(
                    self.adapter.reviewer_actor_id, materials_check_match[1]))
                return
            if validate_match:
                if method != 'POST':
                    await _respond(send, 405, {'error': 'method_not_allowed'}, ((b'allow', b'POST'),))
                    return
                body = await _read_body(receive, send, headers)
                if body is None:
                    return
                try:
                    payload = json.loads(body)
                except (ValueError, UnicodeError) as exc:
                    raise HubError('Invalid result JSON') from exc
                await _respond(send, 200, self.runtime.hub.grok_result_preflight(
                    self.adapter.reviewer_actor_id, validate_match[1], payload))
                return
            if method == 'GET' and materials_match:
                await _respond(send, 200, self.runtime.hub.grok_materials(
                    self.adapter.reviewer_actor_id, materials_match[1]))
                return
            if method == 'GET' and ingress_match:
                await _respond(send, 200, self.runtime.hub.grok_ingress_status(
                    self.adapter.reviewer_actor_id, ingress_match[1]))
                return
            if method == 'GET' and path == _REQUESTS:
                if self.intake is None:
                    raise HubError('Reviewer intake queue is not configured')
                await _respond(send, 200, {'requests': self.intake.list_available()})
                return
            if method == 'GET' and request_match:
                value = self.runtime.hub.grok_request(self.adapter.reviewer_actor_id, request_match[1])
                if self.intake is not None:
                    self.intake.acknowledge(request_match[1])
                await _respond(send, 200, value)
                return
            if method == 'GET' and artifact_match:
                artifact, content = self.runtime.hub.grok_artifact(
                    self.adapter.reviewer_actor_id, artifact_match[1], artifact_match[2])
                if self.intake is not None:
                    try:
                        self.runtime.hub.grok_request(self.adapter.reviewer_actor_id,
                                                      artifact_match[1])
                    except PermissionDenied:
                        # Historical evidence reads must not ACK or revive intake.
                        pass
                    else:
                        self.intake.acknowledge(artifact_match[1])
                await send({'type': 'http.response.start', 'status': 200, 'headers': [
                    (b'content-type', b'application/octet-stream'),
                    (b'content-length', str(len(content)).encode('ascii')),
                    (b'x-content-sha256', artifact['sha256'].encode('ascii'))]})
                await send({'type': 'http.response.body', 'body': content})
                return
            if path != '/reviewer/events':
                await _respond(send, 404, {'error': 'not_found'})
                return
            if method != 'POST':
                await _respond(send, 405, {'error': 'method_not_allowed'}, ((b'allow', b'POST'),))
                return
            body = await _read_body(receive, send, headers)
            if body is None:
                return
            event = self.adapter.normalize_review_event(body, self.adapter.reviewer_actor_id)
            self.runtime.hub.validate_grok_event_route(
                event.actor_id, event.review_request_id, event.task_id, event.review_id)
            ingress_id = self.runtime.events.ingest(event)
            await _respond(send, 202, {'ingress_id': ingress_id, 'status': 'READY'})
        except PermissionDenied:
            await _respond(send, 403, {'error': 'forbidden'})
        except HubError as exc:
            await _respond(send, 422, {'error': exc.code})
