"""Evidence-based collection health; zero accepted items never proves zero news."""
from collections import Counter

LABELS = {'source_failed': '来源失败', 'partial_failure': '部分列表或正文失败',
          'awaiting_body': '元数据已核实，正文待补', 'verified_articles': '有已核实文章',
          'no_articles_in_exposed_feed_window': '已遍历的列表内无窗口文章',
          'no_verified_samples_coverage_incomplete': '无已核实样本，覆盖未完成'}


def markdown(results):
    lines = ['### 直采来源诊断', '',
             '| 来源 | 采集情况 | 核实文章 | 待正文 | 详情失败 |',
             '| --- | --- | --- | --- | --- |']
    for result in results:
        health = summarize(result)
        name = str(result.get('source', {}).get('account_name', '未知来源'))
        name = name.replace('|', '／').replace('\n', ' ').replace('\r', ' ').replace('<', '&lt;')
        lines.append(f'| {name} | {LABELS[health["state"]]} | {health["verifiedArticles"]} | '
                     f'{health["awaitingBodies"]} | {health["detailFailures"]} |')
    return '\n'.join(lines + ['', '统计只说明已观察列表及核实结果，不代表原始发布者24小时无遗漏。', ''])


def summarize(result):
    coverage = result.get('coverage', {})
    items = result.get('items', [])
    issues = result.get('diagnostics', [])
    detail_issues = [x for x in issues if x.get('stage') == 'detail']
    detail_issues += coverage.get('detailFailures', [])
    accepted = {i['url'] for i in items}
    resolved = sum(x.get('url') in accepted for x in detail_issues)
    detail_issues = [x for x in detail_issues if x.get('url') not in accepted]
    list_issues = [x for x in issues if x.get('stage') == 'list']
    bodies = sum(len(i.get('content_text', '').strip()) >= 100 for i in items)
    complete = bool(coverage.get('coverageComplete', coverage.get('complete', False)))
    reasons = Counter(x.get('reason', 'unknown') for x in detail_issues + list_issues)
    if result.get('status') == 'failed':
        state = 'source_failed'
    elif detail_issues or list_issues or coverage.get('rejectedRows', 0):
        state = 'partial_failure'
    elif bodies < len(items):
        state = 'awaiting_body'
    elif items:
        state = 'verified_articles'
    elif complete:
        state = 'no_articles_in_exposed_feed_window'
    else:
        state = 'no_verified_samples_coverage_incomplete'
    return {'state': state, 'adapterReason': result.get('reason'),
            'verifiedArticles': len(items), 'usableBodies': bodies,
            'awaitingBodies': len(items) - bodies,
            'detailFailures': len(detail_issues), 'listFailures': len(list_issues),
            'historicalDetailFailuresResolved': resolved,
            'failureReasons': dict(sorted(reasons.items())),
            'latestVerifiedPublicationAt': max((i['publishedAt'] for i in items), default=None),
            'exposedFeedComplete': complete,
            'originalPublisher24hCoverageVerified': False}
