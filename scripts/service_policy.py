"""Explicit pause switches, enforced before a legacy service reaches HTTP."""
import json
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[1] / 'config/services.json'


def enabled(service):
    if service not in ('manus', 'tavily'):
        raise ValueError('Unknown optional service')
    try:
        policy = json.loads(POLICY_PATH.read_text(encoding='utf-8'))
        return policy.get('schemaVersion') == 1 and policy.get(service) is True
    except (OSError, ValueError, AttributeError):
        return False


def require(service):
    if not enabled(service):
        raise ValueError(f'{service} service is paused by project policy')
