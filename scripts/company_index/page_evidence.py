"""公司网页读取与字段证据门禁；不调用模型、不修改公司记录。"""
import copy
import re
from urllib.parse import urlsplit

from field_value_guard import rejection_reason
from manus_source.crawler import fetch_html, extract_text, truncate_head_tail, _looks_like_risk_page


_AGGREGATE_FUNDING = re.compile(
    r'累计|累积|合计|共计|总计|total\s+(?:funding|raised)|aggregate\s+funding|'
    r'\b(?:has|have)\s+raised\b.{0,120}\bin\s+total\b|'
    r'\b(?:raised|funding)\b.{0,120}\bto\s+date\b', re.I)
_DATA_LOCATION = re.compile(
    r'\bservers?\b|\bdata\s+cent(?:er|re)s?\b|'
    r'\b(?:data|information)\b.{0,80}\b(?:stor(?:age|ed)|transfer(?:red|s)?|process(?:ed|ing)?)\b|'
    r'\b(?:store[ds]?|transfer(?:red)?|process(?:ed|ing)?)\b.{0,50}\b(?:data|information)\b|'
    r'服务器|数据中心|数据.{0,20}(?:存储|传输|转移|处理)|(?:存储|托管|处理|传输).{0,20}数据', re.I)
_COMPANY_LOCATION = re.compile(
    r'headquarters?|head\s+office|registered\s+(?:office|address|in)|incorporat|'
    r'\b(?:offices?|address)\b|总部|办公(?:地点|地址|室)|(?:公司|企业|法人|注册|营业)地址|注册(?:于|在)|登记(?:于|在)', re.I)


def read_page(url):
    """仅读取指定公共HTTPS页面；拒绝跨域跳转和非HTML正文。"""
    host = urlsplit(url).hostname or ''
    if urlsplit(url).scheme != 'https' or urlsplit(url).username or not host or host == 'localhost' or re.fullmatch(r'[\d.:]+', host):
        raise ValueError('需要公共网页域名')
    final, html = fetch_html(url, timeout_seconds=15, retries=0)
    if urlsplit(final).hostname != host:
        raise ValueError('页面跨域跳转，保留待核实')
    text, title = extract_text(html)
    if not text or len(text) < 60 or _looks_like_risk_page(html, text):
        raise ValueError('页面正文不足')
    return {'url': url, 'title': title or host, 'text': truncate_head_tail(text, 14000)}


def eligible_fact(fact, row):
    """引文校验之外的业务门禁；待核实也不能混淆融资口径。"""
    fact = copy.deepcopy(fact)
    field, quote, value = fact['field'], fact.get('quote', ''), fact.get('value', '')
    if field == 'founded' and (not re.search(r'incorporat|注册|登记', quote, re.I) or not re.search(r'\d{4}', value)):
        return None
    if field == 'country' and _DATA_LOCATION.search(quote):
        # Hosting and cross-border data processing describe infrastructure, not
        # the company's location. Keep explicit HQ/office/legal-address evidence.
        location_quote = re.sub(r'\b(?:IP|server|storage)\s+address(?:es)?\b|服务器地址|数据中心地址', '', quote, flags=re.I)
        if not _COMPANY_LOCATION.search(location_quote):
            return None
    if field in ('total_funding', 'valuation'):
        # Enrichment runs after entity merging, so both its proposed scalar and
        # its source quote must satisfy the same financial meaning guard.
        if rejection_reason(field, value):
            return None
        quote_conflict = rejection_reason(field, quote)
        aggregate = field == 'total_funding' and _AGGREGATE_FUNDING.search(quote)
        # A genuine aggregate may mention constituent rounds; a round's own
        # "融资总额" alone never establishes a company-wide aggregate.
        if quote_conflict and not (quote_conflict == 'single_round_not_total' and aggregate):
            return None
        if re.search(r'拟|计划|意向|尚未|寻求|target|seeking|plans? to|in talks', quote+' '+value, re.I):
            return None
        if not re.search(r'\d', value) or not re.search(r'美元|人民币|欧元|英镑|港元|USD|RMB|CNY|EUR|GBP|HKD|\$', value, re.I):
            return None
        if field == 'total_funding' and not (aggregate or re.search(r'融资总额|total.*rais|raised.*total', quote, re.I)):
            return None
    if field == 'team':
        if not any(n and n.casefold() in quote.casefold() for n in [row['company_name'], *row.get('aliases', [])]):
            return None
        if not re.search(r'创始|CEO|首席|团队|总裁|founder|chief|team', quote, re.I):
            return None
        # 人名、履历只保留引文实际支持的部分，不扩写院校和任职。
        fact['value'] = quote[:350]
    return fact
