"""Fixture extraction without subprocesses; explicitly injected only by offline tests."""
import json
import threading
from types import SimpleNamespace
from manus_source.extraction_worker import extract_payload

_lock = threading.Lock()


def fixture_extraction(html_bytes, timeout_seconds, need_metadata):
    # Keep fixture coverage of the parser while avoiding concurrent native state in tests.
    with _lock:
        value = extract_payload(html_bytes, metadata=need_metadata)
    return SimpleNamespace(returncode=0, stdout=json.dumps(value).encode(), stderr=b'')
