"""Offline Phase 0 artifact checks. This is not a Hub or domain implementation."""
from __future__ import annotations

import copy
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / 'docs' / 'contracts'
REQUIRED = [
    'README.md', 'AGENTS.md', 'ARCHITECTURE.md', 'DATA_MODEL.md',
    'STATE_MACHINE.md', 'SECURITY.md', 'REVIEW_PROTOCOL.md', 'IMPLEMENTATION_PLAN.md',
    *['docs/' + name + '.md' for name in (
        'SOURCE_OF_TRUTH', 'ASYNC_REVIEW_SEQUENCE', 'ARTIFACT_MODEL',
        'FINDING_LIFECYCLE', 'GITHUB_ACTORS', 'GITHUB_CONNECTIVITY',
        'VERDICT_RULES', 'PROTOCOL_V1', 'WORKBUDDY_INTEGRATION', 'GROK_BOT_INTEGRATION')],
]
SKILLS = ['architecture-gate', 'phase-execution', 'review-protocol-validator', 'async-workflow-test']
results: list[dict] = []


def check(name: str, passed: bool, detail: str = '') -> None:
    results.append({'check': name, 'passed': bool(passed), 'detail': detail})


def validate_documents(allow_core=False) -> None:
    for rel in REQUIRED:
        path = ROOT / rel
        check('required:' + rel, path.is_file() and path.stat().st_size > 0)
    documents = list(ROOT.glob('*.md')) + list((ROOT / 'docs').rglob('*.md'))
    documents += list((ROOT / 'skills').rglob('*.md'))
    bad_links = []
    for path in documents:
        content = path.read_text(encoding='utf-8')
        for raw in re.findall(r'\[[^\]\n]+\]\(([^)\n]+)\)', content):
            target = raw.strip('<>')
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target) or target.startswith('#'):
                continue
            target = unquote(target.split('#', 1)[0])
            if target and not (path.parent / target).exists():
                bad_links.append(str(path.relative_to(ROOT)) + ' -> ' + target)
    check('relative-markdown-links', not bad_links, '; '.join(bad_links))
    if allow_core:
        check('phase1-local-core-source', (ROOT / 'src/grokbuddy').is_dir())
    else:
        check('phase0-no-core-source', not (ROOT / 'src').exists())
    env = (ROOT / '.env.example').read_text(encoding='utf-8')
    populated = []
    for line in env.splitlines():
        if '=' not in line or line.startswith('#'):
            continue
        key, value = line.split('=', 1)
        if (key.endswith('_TOKEN') or key.endswith('_SECRET')) and value.strip():
            populated.append(key)
    check('example-secrets-empty', not populated, ','.join(populated))
    for name in SKILLS:
        path = ROOT / 'skills' / name / 'SKILL.md'
        if not path.exists():
            check('skill:' + name, False, 'Missing SKILL.md')
            continue
        match = re.match(r'^---\n(.*?)\n---\n', path.read_text(encoding='utf-8'), re.S)
        header = yaml.safe_load(match.group(1)) if match else {}
        check('skill:' + name, isinstance(header, dict) and header.get('name') == name
              and isinstance(header.get('description'), str) and bool(header['description'].strip()))


def validate_contracts() -> None:
    check('date-time-format-checker-active', 'date-time' in FormatChecker().checkers)
    schemas = {p.stem.replace('.schema', ''): json.loads(p.read_text(encoding='utf-8'))
               for p in CONTRACTS.glob('*.schema.json')}
    for name, schema in schemas.items():
        try:
            Draft202012Validator.check_schema(schema)
            check('meta-schema:' + name, True)
        except Exception as exc:
            check('meta-schema:' + name, False, str(exc))
    registry = Registry().with_resources(
        (s['$id'], Resource.from_contents(s)) for s in schemas.values())
    validators = {k: Draft202012Validator(v, registry=registry, format_checker=FormatChecker())
                  for k, v in schemas.items()}
    fixtures = {}
    for path in sorted((CONTRACTS / 'examples').glob('*.json')):
        data = json.loads(path.read_text(encoding='utf-8'))
        kind = 'review-request' if path.stem.endswith('request') else (
            'final-package' if path.stem == 'final-package' else 'review-result')
        validator = validators[kind]
        fixtures[path.stem] = (data, validator)
        errors = list(validator.iter_errors(data))
        check('positive:' + path.stem, not errors, '; '.join(e.message for e in errors))
        # Exercise the published required-field contract, including oneOf branches.
        optional = {'commit_sha', 'diff_artifact'} if kind == 'final-package' else set()
        for field in data:
            if field in optional:
                continue
            candidate = copy.deepcopy(data)
            del candidate[field]
            check('missing:' + path.stem + ':' + field, not validator.is_valid(candidate))
        candidate = copy.deepcopy(data)
        candidate['unexpected_field'] = 'reject'
        check('unknown-field:' + path.stem, not validator.is_valid(candidate))

    def reject(fixture: str, name: str, mutate) -> None:
        data, validator = fixtures[fixture]
        candidate = copy.deepcopy(data)
        mutate(candidate)
        check('negative:' + name, not validator.is_valid(candidate))

    for fixture in ('plan-request', 'final-result'):
        for field, value in [('protocol_version', 'v2'), ('review_round', 0),
                             ('review_round', True), ('content_revision', -1),
                             ('review_type', 'FINAL'), ('input_sha256', 'broken'),
                             ('review_profile', 'invented'), ('task_id', 'TASK-R001')]:
            reject(fixture, fixture + ':' + field + ':' + str(value),
                   lambda d, f=field, v=value: d.__setitem__(f, v))
    reject('final-result', 'invalid-verdict', lambda d: d.__setitem__('verdict', 'PASSED'))
    reject('final-result', 'invalid-date', lambda d: d.__setitem__('timestamp', 'yesterday'))
    reject('final-result', 'empty-summary', lambda d: d.__setitem__('summary', ''))
    reject('final-result', 'oversize-summary', lambda d: d.__setitem__('summary', 'x' * 2001))
    reject('final-result', 'severity', lambda d: d['findings'][0].__setitem__('severity', 'URGENT'))
    reject('final-result', 'blocking-string', lambda d: d['findings'][0].__setitem__('blocking', 'true'))
    reject('final-result', 'no-evidence', lambda d: d['findings'][0].pop('evidence'))
    reject('final-result', 'reviewer-sets-status', lambda d: d['findings'][0].__setitem__('status', 'VERIFIED'))
    reject('final-result', 'reviewer-sets-new-primary-key', lambda d: d['findings'][0].__setitem__('finding_id', 'FND-R001'))
    reject('final-result', 'mixed-plan-final', lambda d: d.__setitem__('comments', []))
    reject('plan-result', 'mixed-final-plan', lambda d: d.__setitem__('findings', []))
    reject('final-verification', 'verification-verdict', lambda d: d['verifications'][0].__setitem__('outcome', 'PASS'))
    reject('final-package', 'missing-diff-and-commit', lambda d: d.pop('diff_artifact'))
    reject('final-package', 'missing-test-artifacts', lambda d: d.__setitem__('test_results', []))
    # Ensure refs actually constrain nested evidence/identity rather than silently accepting.
    reject('final-result', 'nested-evidence-id', lambda d: d['findings'][0]['evidence'].__setitem__('artifact_id', '../secret'))
    reject('final-result', 'nested-reviewer-unknown-field', lambda d: d['reviewer'].__setitem__('is_human', True))


def main() -> int:
    parser = argparse.ArgumentParser(description='Validate design contracts; historical Phase 0 results are preserved.')
    parser.add_argument('--allow-core', action='store_true', help='Run the contract checks for an authorized implementation phase')
    args = parser.parse_args()
    validate_documents(args.allow_core)
    validate_contracts()
    failed = [r for r in results if not r['passed']]
    digest_paths = sorted(list(CONTRACTS.rglob('*.json')) + list((ROOT / 'skills').rglob('SKILL.md')))
    report = {
        'scope': 'PHASE1_CONTRACT_REGRESSION' if args.allow_core else 'PHASE0_OFFLINE_DOCUMENT_AND_CONTRACT_CHECKS',
        'total': len(results), 'passed': len(results) - len(failed), 'failed': len(failed),
        'external_environment_gate': 'BLOCKED',
        'not_run_by_this_checker': ['Hub runtime', 'SQLite domain transactions', 'MockReviewer workflow',
                    'WorkBuddy MCP handshake', 'Grok Bot trigger', 'GitHub API/Webhook/Pull',
                    'production permissions', 'business demos'],
        'checks': results,
        'input_sha256': {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in digest_paths},
    }
    output = ROOT / 'docs' / ('phase1-contract-checks.json' if args.allow_core else 'phase0-checks.json')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Contract checks: {report['passed']}/{report['total']} passed; {len(failed)} failed")
    for item in failed:
        print('FAIL:', item['check'], item['detail'])
    print('External environment gate: BLOCKED (no live integrations executed)')
    print('Evidence:', output)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
