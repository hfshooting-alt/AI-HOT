"""Read-only fixed article probe; never calls Manus/LLMs or writes production data."""
import json
from manus_source.crawler import crawl_one
from manus_source.rendered_page import fetch_article
from manus_source.contracts import validate_content_batch, content_sha256


def main():
    article = {'account_name': '机器之心', 'author': None,
               'article_url': 'https://jigou.jiqizhixin.com/articles/2026-09-17-11',
               'published_date': '2026-09-17',
               'title': '开源模型夯爆了！ZDTaichu5.0-9B，10B以内空间具身智能卷出通用类第一'}
    result = crawl_one(article, '2026-09-18', retries=0, timeout_seconds=25, render_fn=fetch_article)
    ok, failed = validate_content_batch({'target_date': '2026-09-18', 'articles': [result]},
        '2026-09-18', {article['article_url']: article['title']}, 100,
        {article['article_url']: article['published_date']})
    print(json.dumps({'contentStatus': result['content_status'],
        'contentCharacters': len(result['content_text']),
        'contentSha256': content_sha256(result['content_text']),
        'accepted': len(ok), 'failures': failed}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
