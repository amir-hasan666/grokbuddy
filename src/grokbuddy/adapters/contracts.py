import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
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

    def validate(self, kind, value):
        if not self.validators[kind].is_valid(value):
            # Do not include invalid payloads, credentials or raw schema errors in logs.
            raise HubError(f'Invalid {kind} contract')
