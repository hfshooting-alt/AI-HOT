"""Public reason codes derived from private collection audits; no raw logs exposed."""


def reason_code(status, note):
    note = str(note or '').lower()
    if status == 'not_requested':
        return 'not_requested'
    if 'cost_circuit_open' in note and 'task not created' in note:
        return 'not_started_budget'
    if 'credit' in note and ('threshold' in note or 'limit' in note or 'stop' in note):
        return 'budget_stopped'
    if status == 'complete':
        return 'complete'
    for code in ('identity_mismatch', 'list_not_loaded', 'detail_time_unavailable', 'boundary_unverified'):
        if code in note:
            return code
    return 'partial' if status == 'partial' else 'unavailable'
