"""Verify a signed, current WorkBuddy user message before creating a Hub Task.

The message signature is issued by a trusted WorkBuddy ingress, not by the
model invoking create_task. No signature key means no production creation.
Offsets are UTF-8 byte offsets in the concatenated, unmodified segments.
"""

import hashlib
import hmac
import re

from grokbuddy.domain.model import (TriggerEvidenceInvalid, TriggerNotFound,
                                    TriggerSourceUnavailable)

from .common import canonical


PHRASE = '启用grokbuddy流程'
MESSAGE_FIELDS = {'principal_id', 'conversation_id', 'message_id', 'turn_id',
                  'message_role', 'issued_at', 'segments'}
EVIDENCE_FIELDS = {'message', 'signature', 'body_sha256', 'phrase',
                   'start_byte', 'end_byte'}
SEGMENT_SOURCES = {'user_body', 'code_block', 'quote', 'pasted_document',
                   'attachment', 'tool_output'}
FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})')
QUOTE = re.compile(r'^ {0,3}>')
INDENTED_CODE = re.compile(r'^(?: {4}|\t)')
BACKTICKS = re.compile(r'`+')
HEX_SHA256 = re.compile(r'[0-9a-f]{64}\Z')


def _invalid():
    raise TriggerEvidenceInvalid('Trusted current user message evidence is invalid')


def _identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 200 and value.strip() == value


def _inline_code_ranges(line):
    runs = list(BACKTICKS.finditer(line))
    ranges = []
    index = 0
    while index < len(runs):
        opener = runs[index]
        match = next((i for i in range(index + 1, len(runs))
                      if len(runs[i].group()) == len(opener.group())), None)
        if match is None:
            ranges.append((opener.start(), len(line)))
            break
        ranges.append((opener.start(), runs[match].end()))
        index = match + 1
    return ranges


def _eligible_spans(segments):
    """Find exact phrase bytes only in top-level natural-language body lines."""
    found = []
    byte_base = 0
    fence_char = None
    fence_length = 0
    # A transport may split one natural-language body into adjacent segments.
    # Coalesce only adjacent body pieces, never across excluded provenance.
    joined = []
    for segment in segments:
        if segment['source'] == 'user_body' and joined and joined[-1]['source'] == 'user_body':
            joined[-1]['text'] += segment['text']
        else:
            joined.append(dict(segment))
    for segment in joined:
        source, value = segment['source'], segment['text']
        if source != 'user_body':
            byte_base += len(value.encode('utf-8'))
            continue
        for line in value.splitlines(keepends=True):
            marker = FENCE.match(line)
            if fence_char is not None:
                if marker and marker.group(1)[0] == fence_char and len(marker.group(1)) >= fence_length:
                    fence_char = None
                byte_base += len(line.encode('utf-8'))
                continue
            if marker:
                fence_char, fence_length = marker.group(1)[0], len(marker.group(1))
                byte_base += len(line.encode('utf-8'))
                continue
            if not QUOTE.match(line) and not INDENTED_CODE.match(line):
                excluded = _inline_code_ranges(line)
                position = line.find(PHRASE)
                while position >= 0:
                    end = position + len(PHRASE)
                    if not any(position < right and end > left for left, right in excluded):
                        start_byte = byte_base + len(line[:position].encode('utf-8'))
                        found.append((start_byte, start_byte + len(PHRASE.encode('utf-8'))))
                    position = line.find(PHRASE, position + 1)
            byte_base += len(line.encode('utf-8'))
        # splitlines yields no line for an empty segment.
    return found


def _validated_message(message, description, actor_id, now):
    if not isinstance(message, dict) or set(message) != MESSAGE_FIELDS:
        _invalid()
    if not all(_identifier(message.get(name)) for name in
               ('principal_id', 'conversation_id', 'message_id', 'turn_id')):
        _invalid()
    if message['principal_id'] != actor_id or message['message_role'] != 'user':
        _invalid()
    issued_at = message['issued_at']
    if type(issued_at) is not int or issued_at > now + 30_000_000 or issued_at < now - 300_000_000:
        _invalid()
    segments = message['segments']
    if not isinstance(segments, list) or not 1 <= len(segments) <= 100:
        _invalid()
    for segment in segments:
        if (not isinstance(segment, dict) or set(segment) != {'source', 'text'}
                or not isinstance(segment['source'], str)
                or segment['source'] not in SEGMENT_SOURCES
                or not isinstance(segment['text'], str)):
            _invalid()
    body = ''.join(segment['text'] for segment in segments)
    if (len(body.encode('utf-8')) > 256 * 1024
            or (description is not None and body != description)):
        _invalid()
    return body, segments


def issue_trigger_evidence(message, source_key, now):
    """Sign one connector-attested WorkBuddy message for the Hub's second check."""
    if not isinstance(source_key, bytes) or len(source_key) < 32:
        raise TriggerSourceUnavailable('Trusted WorkBuddy trigger source is not configured')
    body, segments = _validated_message(
        message, None, message.get('principal_id') if isinstance(message, dict) else None, now)
    spans = _eligible_spans(segments)
    if not spans:
        raise TriggerNotFound('Current user natural-language body has no exact trigger phrase')
    message_bytes = canonical(message)
    start, end = spans[0]
    evidence = {
        'message': message,
        'signature': hmac.new(source_key, message_bytes, hashlib.sha256).hexdigest(),
        'body_sha256': hashlib.sha256(body.encode('utf-8')).hexdigest(),
        'phrase': PHRASE,
        'start_byte': start,
        'end_byte': end,
    }
    # Issuance and intake deliberately use the same structural and provenance
    # validation. TaskService still verifies this evidence again in its own
    # create transaction.
    verify_trigger(evidence, body, message['principal_id'], source_key, now)
    return body, evidence


def verify_trigger(evidence, description, actor_id, source_key, now):
    """Return frozen, raw-text-free metadata and the signed message artifact bytes."""
    if not isinstance(source_key, bytes) or len(source_key) < 32:
        raise TriggerSourceUnavailable('Trusted WorkBuddy trigger source is not configured')
    if not isinstance(evidence, dict) or set(evidence) != EVIDENCE_FIELDS:
        _invalid()
    message = evidence['message']
    body, segments = _validated_message(message, description, actor_id, now)
    if not isinstance(evidence['signature'], str) or not HEX_SHA256.fullmatch(evidence['signature']):
        _invalid()
    message_bytes = canonical(message)
    expected = hmac.new(source_key, message_bytes, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, evidence['signature']):
        _invalid()
    if (evidence['body_sha256'] != hashlib.sha256(body.encode('utf-8')).hexdigest()
            or evidence['phrase'] != PHRASE):
        _invalid()
    spans = _eligible_spans(segments)
    if not spans:
        raise TriggerNotFound('Current user natural-language body has no exact trigger phrase')
    start, end = evidence['start_byte'], evidence['end_byte']
    if type(start) is not int or type(end) is not int or start < 0 or end <= start:
        _invalid()
    if (start, end) not in spans:
        _invalid()
    frozen = {
        'principal_id': actor_id,
        'conversation_id': message['conversation_id'],
        'message_id': message['message_id'],
        'turn_id': message['turn_id'],
        'issued_at': message['issued_at'],
        'body_sha256': evidence['body_sha256'],
        'source_sha256': hashlib.sha256(message_bytes).hexdigest(),
        'signature': evidence['signature'],
        'phrase': PHRASE,
        'start_byte': start,
        'end_byte': end,
        'segment_sources': [segment['source'] for segment in segments],
    }
    return frozen, message_bytes
