import json
import re
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import best_match
from referencing import Registry, Resource
from grokbuddy.domain.model import HubError


class JsonContracts:
    def __init__(self, directory):
        schemas = [json.loads(p.read_text(encoding='utf-8'))
                   for p in Path(directory).glob('*.schema.json')]
        if len(schemas) != 4 or 'date-time' not in FormatChecker().checkers:
            raise RuntimeError('Contract schemas/date-time validator unavailable')
        registry = Registry().with_resources((s['$id'], Resource.from_contents(s)) for s in schemas)
        self.validators = {}
        for schema in schemas:
            Draft202012Validator.check_schema(schema)
            key = schema['$id'].split(':')[2]
            self.validators[key] = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())

    def error_path(self, kind, value):
        """Return only a safe schema location, never invalid values or messages."""
        validator = self.validators['common'].evolve(schema={
            '$ref': 'urn:collab:common:v1#/$defs/plan_scope_snapshot_v1'
        }) if kind == 'plan-scope-snapshot' else self.validators[kind]
        return self._error_path(validator, kind, value)

    def final_materials_error_path(self, value):
        # Pre-submission fields use the exact package contract. Only the profile
        # snapshot ID is absent: the gateway creates it after self-test succeeds.
        schema = dict(self.validators['final-package'].schema)
        schema['required'] = [field for field in schema['required']
                              if field != 'profile_artifact_id']
        return self._error_path(self.validators['final-package'].evolve(schema=schema),
                                'final-package', value)

    def _error_path(self, validator, kind, value):
        if (kind == 'result' and isinstance(value, dict)
                and value.get('protocol_version') not in ('v1', 'v2')):
            return '$.protocol_version'
        error = best_match(validator.iter_errors(value))
        if error is None:
            return None
        if (error.validator == 'oneOf' and isinstance(value, dict) and error.context
                and kind == 'result'):
            branch = (0 if value.get('review_type') == 'PLAN_REVIEW' else 1)
            if value.get('protocol_version') == 'v2':
                branch = 2
            relevant = [child for child in error.context
                        if child.schema_path and child.schema_path[0] == branch]
            error = best_match(relevant) or error
        parts = list(error.absolute_path)
        if error.validator == 'required' and isinstance(error.instance, dict):
            missing = [name for name in error.validator_value
                       if name not in error.instance]
            if missing:
                parts.append(missing[0])
        safe = []
        for part in parts:
            if isinstance(part, int) and part >= 0:
                safe.append(f'[{part}]')
            elif isinstance(part, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', part):
                safe.append('.' + part)
            else:
                return '$'
        return '$' + ''.join(safe)

    def validate(self, kind, value):
        if self.error_path(kind, value) is not None:
            # Do not include invalid payloads, credentials or raw schema errors in logs.
            raise HubError(f'Invalid {kind} contract')

    def bundle(self):
        """Expose every registered dependency so remote validation is self-contained."""
        return {validator.schema['$id']: validator.schema
                for validator in self.validators.values()}
