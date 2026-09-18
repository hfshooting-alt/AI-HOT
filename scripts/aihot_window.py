"""AIHOT's timeline window, independent of Manus original-publication rules."""
from datetime import timedelta

from manus_source.window import timestamp


def timeline_at(item):
    published = item.get('publishedAt')
    discovered = item.get('discoveredAt')
    if not discovered:
        return timestamp(published)
    found = timestamp(discovered)
    if not published:
        return found
    original = timestamp(published)
    # AIHOT assigns backfills older than 72 hours to the original date.
    return original if found - original > timedelta(hours=72) else found


def in_window(window, item):
    try:
        return timestamp(window['start']) <= timeline_at(item) < timestamp(window['end'])
    except (ValueError, TypeError, KeyError):
        return False
