"""Short AIHOT facts may be classified without inventing a longer article."""


def is_brief(item):
    content = (item.get('content_text') or '').strip()
    return item.get('evidenceKind') == 'upstream_title_summary' and 4 <= len(content) < 50


def source_text(item):
    summary = (item.get('summary') or '').strip()
    return summary if len(summary) >= 4 else (item.get('title') or '').strip()
