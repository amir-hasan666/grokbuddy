from pathlib import Path
import ast
import pytest

from grokbuddy.domain.model import TaskState, FindingStatus, Role, IllegalTransition, Settings
from grokbuddy.domain.rules import TASK_EDGES, transition, finding_transition, aggregate_verdict


ILLEGAL = [(s.value, event) for s in TaskState for event, (origins, _) in TASK_EDGES.items() if s not in origins]


@pytest.mark.parametrize('state,event', ILLEGAL)
def test_all_unspecified_task_edges_are_rejected(state, event):
    with pytest.raises(IllegalTransition):
        transition(state, event)


@pytest.mark.parametrize('status,expected', [('OPEN','BLOCK'),('ACCEPTED','BLOCK'),('FIXED','BLOCK'),
    ('REJECTED_WITH_EVIDENCE','BLOCK'),('VERIFIED','PASS'),('WAIVED_BY_HUMAN','PASS')])
def test_critical_aggregation(status, expected):
    assert aggregate_verdict([{'status': status, 'severity': 'CRITICAL'}], 'PASS') == expected


@pytest.mark.parametrize('severity', ['HIGH', 'MEDIUM', 'LOW'])
@pytest.mark.parametrize('status', ['OPEN', 'ACCEPTED', 'FIXED', 'REJECTED_WITH_EVIDENCE'])
def test_all_noncritical_unclosed_states_prevent_pass(severity, status):
    assert aggregate_verdict([{'status': status, 'severity': severity, 'blocking': True}], 'PASS') == 'NEEDS_CHANGES'


def test_reported_verdict_never_downgraded():
    assert aggregate_verdict([], 'BLOCK') == 'BLOCK'
    assert aggregate_verdict([], 'NEEDS_CHANGES') == 'NEEDS_CHANGES'


@pytest.mark.parametrize('role', [Role.BUILDER, Role.HUMAN, Role.SYSTEM])
def test_only_reviewer_can_verify(role):
    with pytest.raises(IllegalTransition):
        finding_transition('FIXED', 'verify', role)


@pytest.mark.parametrize('role', [Role.BUILDER, Role.REVIEWER, Role.SYSTEM])
def test_only_human_can_waive(role):
    with pytest.raises(IllegalTransition):
        finding_transition('OPEN', 'waive', role)


def test_enum_and_settings_boundaries():
    assert len(TaskState) == 19
    assert TaskState.PLAN_HUMAN_REVIEW.value == 'PLAN_HUMAN_REVIEW'
    assert TaskState.FINAL_HUMAN_REVIEW.value == 'FINAL_HUMAN_REVIEW'
    with pytest.raises(ValueError):
        TaskState('PASS')
    with pytest.raises(ValueError):
        FindingStatus('BLOCK')
    with pytest.raises(ValueError):
        Settings(max_plan_review_rounds=0)


def test_domain_and_application_dependency_boundaries():
    root = Path(__file__).resolve().parents[1] / 'src/grokbuddy'
    for directory in ('domain', 'application'):
        for path in (root / directory).glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                names = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module or ''] if isinstance(node, ast.ImportFrom) else []
                assert not any(any(x in name for x in ('sqlite3', 'httpx', 'mcp', 'grokbuddy.adapters')) for name in names), path
    mock = (root / 'adapters/mock.py').read_text(encoding='utf-8')
    assert 'repo.' not in mock and '.change(' not in mock and '.review(' not in mock
