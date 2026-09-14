"""Review and promote an existing candidate without collection or model calls.

Imported candidates remain explicitly identified as reviewed imports, never as
successful re-executions of the original collector run.
"""
import json
import hashlib
import os
import shutil
import uuid
from pathlib import Path

from .publish import ALLOWED, publish, save
from .runner import tree_digest, validate_candidates

STAGES = ['news', 'snapshot', 'overview', 'funding']


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def validate(workspace, root):
    validate_candidates(workspace, root, STAGES)
    processed = read(workspace / 'inputs/processed.json')
    snapshot = read(workspace / 'web/public/snapshot.json')
    feed = read(workspace / 'data/manus/current.json')
    status = processed['collectionStatus']
    window = processed['collectionWindow']
    if any(data.get('collectionStatus') != status for data in (snapshot, feed)):
        raise ValueError('候选各产物信源状态不一致')
    if snapshot.get('collectionWindow') != window or status.get('collectionWindow') != window:
        raise ValueError('候选窗口不一致')
    articles = processed['items']
    ids = {a['id'] for a in articles}
    visible = snapshot['all']['items']
    if len(ids) != len(articles) or len(visible) != len(ids) or {a['id'] for a in visible} != ids:
        raise ValueError('候选新闻与网页文章集合不一致')
    by_id = {a['id']: a for a in articles}
    for article in visible:
        if any(article.get(k) != by_id[article['id']].get(k) for k in ('title', 'summary', 'url', 'publishedAt')):
            raise ValueError('候选新闻与网页内容不一致')
    if status['publishedArticles'] != len(ids) or status['quarantinedArticles'] != len(status['quarantined']):
        raise ValueError('候选新闻计数不一致')
    if status['candidateArticles'] != len(ids) + status['excludedArticles'] + status['quarantinedArticles']:
        raise ValueError('候选收录去向计数不一致')
    if ids.intersection(a['id'] for a in status['quarantined']):
        raise ValueError('隔离文章混入候选新闻')
    overview = read(workspace / 'data/company-overview/current.json')
    if overview['stats']['articlesProcessed'] != len(ids):
        raise ValueError('公司处理范围与候选新闻不一致')
    current = root / 'web/public/snapshot.json'
    if current.exists():
        current_end = (read(current).get('collectionWindow') or {}).get('end', '')
        if current_end and window['end'] < current_end:
            raise ValueError('禁止较旧批次覆盖较新的正式网页')
    return {'window': window, 'news': len(ids), 'quarantined': status['quarantinedArticles'],
            'companies': overview['stats']['companiesTotal']}


def safe_tree(path):
    if not path.is_dir() or path.is_symlink():
        raise ValueError('候选目录不存在或包含链接')
    if any(p.is_symlink() or not p.resolve().is_relative_to(path.resolve()) for p in path.rglob('*')):
        raise ValueError('候选包含工作目录外链接')


def code_digest(root):
    digest = hashlib.sha256()
    for folder in ('scripts', 'config'):
        for path in sorted((root / folder).rglob('*')):
            if path.is_file() and path.suffix in ('.py', '.json', '.md', '.html'):
                digest.update(path.relative_to(root).as_posix().encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


def prepare(root: Path, workspace: Path):
    workspace = workspace.resolve()
    if not workspace.is_relative_to((root / 'work').resolve()):
        raise ValueError('只接受本项目work目录中的候选')
    safe_tree(workspace)
    for rel in (*ALLOWED, 'inputs'):
        safe_tree(workspace / rel)
    baseline = {rel: tree_digest(root / rel) for rel in ALLOWED}
    summary = validate(workspace, root)
    run_dir = root / 'work/reviewed-candidates' / uuid.uuid4().hex
    run_dir.mkdir(parents=True)
    for rel in (*ALLOWED, 'inputs'):
        shutil.copytree(workspace / rel, run_dir / 'workspace' / rel)
    validate(run_dir / 'workspace', root)
    if baseline != {rel: tree_digest(root / rel) for rel in ALLOWED}:
        raise ValueError('审核期间正式数据变化，请重建候选')
    manifest = {'kind': 'reviewed_import', 'sourceWorkspace': str(workspace), 'summary': summary,
                'baseline': baseline,
                'candidate': {rel: tree_digest(run_dir / 'workspace' / rel) for rel in (*ALLOWED, 'inputs')},
                'code': code_digest(root), 'published': False}
    save(run_dir / 'review.json', manifest)
    return run_dir, summary


def promote(root: Path, run_dir: Path):
    run_dir = run_dir.resolve()
    if run_dir.parent != (root / 'work/reviewed-candidates').resolve():
        raise ValueError('发布记录不在reviewed-candidates目录')
    lock = root / 'work/pipeline.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        review = read(run_dir / 'review.json')
        journal = run_dir / 'publication.json'
        if journal.exists():
            if read(journal)['status'] == 'committed':
                return review['summary']
            raise ValueError('此前发布中断；先检查并恢复publication.json，禁止重复覆盖')
        if review['kind'] != 'reviewed_import' or review['code'] != code_digest(root):
            raise ValueError('代码或配置已变化，请重新审核候选')
        safe_tree(run_dir / 'workspace')
        if any(tree_digest(run_dir / 'workspace' / rel) != review['candidate'][rel] for rel in (*ALLOWED, 'inputs')):
            raise ValueError('候选文件已变化，请重新审核')
        if any(tree_digest(root / rel) != review['baseline'][rel] for rel in ALLOWED):
            raise ValueError('正式数据已变化，禁止覆盖；请重建候选')
        summary = validate(run_dir / 'workspace', root)
        publish(root, run_dir, list(ALLOWED))
        review['published'] = True
        save(run_dir / 'review.json', review)
        return summary
    finally:
        lock.unlink()
