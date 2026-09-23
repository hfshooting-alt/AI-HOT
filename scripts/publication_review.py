"""Manus uses original publication time; AIHOT batches bypass this review."""
from manus_source.window import matching_item


def review(items, window):
    accepted, isolated = [], []
    for item in items:
        collectors = {item.get('collector')}
        collectors.update(ref.get('collector') for ref in item.get('sourceRefs', []))
        # Shared articles collected by AIHOT retain AIHOT's admission policy.
        if 'aihot' in collectors or not collectors.intersection({'manus', 'direct_site'}) or matching_item(window, item):
            accepted.append(item)
        else:
            isolated.append({'id': item['id'], 'title': item['title'], 'url': item['url'],
                'stage': 'publication_time',
                'reason': 'Manus原始发布时间不符合窗口或无法核实；点赞、评论与更新时间不作为收录依据。'})
    return accepted, isolated
