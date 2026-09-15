"""公司网页读取与字段证据门禁；不调用模型、不修改公司记录。"""
import copy
import re
from urllib.parse import urlsplit

from manus_source.crawler import fetch_html, extract_text, truncate_head_tail, _looks_like_risk_page


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
    if field in ('total_funding', 'valuation'):
        if re.search(r'拟|计划|意向|尚未|寻求|target|seeking|plans? to|in talks', quote+' '+value, re.I):
            return None
        if not re.search(r'\d', value) or not re.search(r'美元|人民币|欧元|英镑|港元|USD|RMB|CNY|EUR|GBP|HKD|\$', value, re.I):
            return None
        if field == 'total_funding' and not re.search(r'累计|融资总额|total.*rais|raised.*total', quote, re.I):
            return None
    if field == 'team':
        if not any(n and n.casefold() in quote.casefold() for n in [row['company_name'], *row.get('aliases', [])]):
            return None
        if not re.search(r'创始|CEO|首席|团队|总裁|founder|chief|team', quote, re.I):
            return None
        # 人名、履历只保留引文实际支持的部分，不扩写院校和任职。
        fact['value'] = quote[:350]
    return fact
