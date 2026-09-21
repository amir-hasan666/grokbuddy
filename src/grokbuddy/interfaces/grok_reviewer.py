"""Dedicated, token-authenticated Grok Reviewer read and event ingress surface."""

import json
import re
import secrets

from grokbuddy.domain.model import HubError, PermissionDenied


_REQUEST = re.compile(r"/reviewer/requests/(RR-[A-Za-z0-9-]+)\Z")
_ARTIFACT = re.compile(r"/reviewer/requests/(RR-[A-Za-z0-9-]+)/artifacts/(ART-[A-Za-z0-9-]+)\Z")
MAX_EVENT_BODY = 1024 * 1024


async def _respond(send, status, body, headers=()):
    data = json.dumps(body, ensure_ascii=False, sort_keys=True).encode('utf-8')
    await send({'type': 'http.response.start', 'status': status,
                'headers': [(b'content-type', b'application/json; charset=utf-8'),
                            (b'content-length', str(len(data)).encode('ascii')), *headers]})
    await send({'type': 'http.response.body', 'body': data})


class GrokReviewerApplication:
    def __init__(self, runtime, adapter, token):
        if not isinstance(token, str) or not token or '\r' in token or '\n' in token:
            raise HubError('Dedicated Grok Reviewer token is required')
        self.runtime, self.adapter = runtime, adapter
        self.expected = ('Bearer ' + token).encode('utf-8')

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await _respond(send, 404, {'error': 'not_found'})
            return
        headers = scope.get('headers', [])
        auth = [v for k, v in headers if k.lower() == b'authorization']
        if len(auth) != 1 or not secrets.compare_digest(auth[0], self.expected):
            await _respond(send, 401, {'error': 'unauthorized'}, ((b'www-authenticate', b'Bearer'),))
            return
        path, method = scope.get('path', ''), scope.get('method')
        artifact_match = _ARTIFACT.fullmatch(path)
        request_match = _REQUEST.fullmatch(path)
        try:
            if method == 'GET' and request_match:
                value = self.runtime.hub.grok_request(self.adapter.reviewer_actor_id, request_match[1])
                await _respond(send, 200, value)
                return
            if method == 'GET' and artifact_match:
                artifact, content = self.runtime.hub.grok_artifact(
                    self.adapter.reviewer_actor_id, artifact_match[1], artifact_match[2])
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
            lengths = [v for k, v in headers if k.lower() == b'content-length']
            try:
                length = int(lengths[0]) if len(lengths) == 1 else -1
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_EVENT_BODY:
                await _respond(send, 413, {'error': 'invalid_length'})
                return
            body = bytearray()
            more = True
            while more and len(body) <= length:
                part = await receive()
                chunk = part.get('body', b'')
                if len(body) + len(chunk) > length:
                    await _respond(send, 413, {'error': 'body_exceeds_declared_length'})
                    return
                body.extend(chunk)
                more = part.get('more_body', False)
            if len(body) != length:
                await _respond(send, 400, {'error': 'body_length_mismatch'})
                return
            event = self.adapter.normalize_review_event(bytes(body), self.adapter.reviewer_actor_id)
            self.runtime.hub.validate_grok_event_route(
                event.actor_id, event.review_request_id, event.task_id, event.review_id)
            ingress_id = self.runtime.events.ingest(event)
            await _respond(send, 202, {'ingress_id': ingress_id, 'status': 'READY'})
        except PermissionDenied:
            await _respond(send, 403, {'error': 'forbidden'})
        except HubError as exc:
            await _respond(send, 422, {'error': exc.code})
