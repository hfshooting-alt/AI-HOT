"""Encrypted CI checkpoints and cache-only recovery; never run collectors."""
import argparse
import base64
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import uuid
import zipfile
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .publish import ALLOWED, save
from .candidate import safe_tree, prepare, code_digest

MAGIC = b'AIHOT-RECOVERY-1\n'
LIMIT = 512 * 1024 * 1024
# Exact operational directories only: no checkout, .env, executables or node_modules.
TREES = ('work/runs', 'work/manus', 'work/company-web-research', 'work/company-discovery',
         'work/company-research-budget')
EXTRA_FILES = ('work/llm-usage.jsonl', 'work/llm-failures.jsonl',
               'work/diagnostic-summary.json', 'work/schedule-audit.json',
               'work/publication-receipt.json')


def cipher(secret, salt):
    if not secret or len(secret) < 20:
        raise ValueError('恢复密钥缺失或过短，禁止保存明文备份')
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt,
               info=b'ai-hot-pipeline-recovery-v1').derive(secret.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def allowed(name):
    p = PurePosixPath(name)
    suffixes = ('.json', '.jsonl', '.html')
    # Legacy per-request reservations also prevent retrying a failed paid call.
    # Do not broaden this to arbitrary .attempt files or other operational trees.
    research_attempt = bool(re.fullmatch(
        r'(?:work/company-web-research/(?:[^/]+/)*|'
        r'work/company-research-budget/model-cache/\d{4}-\d{2}-\d{2}/)[0-9a-f]{64}\.attempt', name))
    if '/workspace/web/public/' in name or '/backup/web/public/' in name:
        suffixes += ('.svg', '.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.woff', '.woff2', '.txt', '.webmanifest')
    return (not p.is_absolute() and '\\' not in name and ':' not in name
            and all(v not in ('.', '..') and not v.startswith('.') for v in p.parts)
            and (p.suffix in suffixes or research_attempt)
            and (name in EXTRA_FILES or any(name.startswith(prefix + '/') for prefix in TREES)))


def pack(root, output, secret):
    salt = os.urandom(16)
    crypt = cipher(secret, salt)  # Fail before scanning when no secret is available.
    files, total, paths = {}, 0, {}
    for prefix in TREES:
        folder = root / prefix
        if not folder.exists():
            continue
        safe_tree(folder)
        paths.update({p.relative_to(root).as_posix(): p for p in folder.rglob('*')
                      if p.is_file() and allowed(p.relative_to(root).as_posix())})
    for name in EXTRA_FILES:
        path = root / name
        if path.is_file():
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('恢复文件链接越出工作目录')
            paths[name] = path
    # Local promotion moves workspace directories into the checkout. Retain
    # those outputs too, including when the later git push/deployment failed.
    for journal in (root / 'work/runs').glob('**/publication.json'):
        publication = json.loads(journal.read_text(encoding='utf-8'))
        if publication.get('status') != 'committed':
            continue
        state = json.loads((journal.parent / 'state.json').read_text(encoding='utf-8'))
        from .runner import tree_digest
        for entry in publication['entries']:
            if entry['path'] not in ALLOWED:
                raise ValueError('发布记录路径无效')
            folder = root / entry['path']
            safe_tree(folder)
            if state.get('publishedOutputs', {}).get(entry['path']) != tree_digest(folder):
                raise ValueError('晋升后数据缺少校验值或已变化，不能标作原运行结果保存')
            for path in folder.rglob('*'):
                name = (journal.parent / 'workspace' / path.relative_to(root)).relative_to(root).as_posix()
                if path.is_file() and allowed(name):
                    paths[name] = path
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(paths.items()):
            total += path.stat().st_size
            if total > LIMIT:
                raise ValueError('恢复包超过大小上限')
            data = path.read_bytes()
            secrets = [secret, *(os.getenv(k, '') for k in ('MANUS_API_KEY', 'DEEPSEEK_API_KEY', 'PARATERA_API_KEY', 'TAVILY_API_KEY'))]
            if any(s and len(s) >= 12 and s.encode() in data for s in secrets):
                raise ValueError('恢复文件包含密钥，停止打包')
            files[name] = hashlib.sha256(data).hexdigest()
            archive.writestr(name, data)
        if not files:
            raise ValueError('没有可保存的流水线产物')
        manifest = {'version': 1, 'files': files, 'code': code_digest(root),
                    'githubRunId': os.getenv('GITHUB_RUN_ID', ''),
                    'githubSha': os.getenv('GITHUB_SHA', '')}
        archive.writestr('manifest.json', json.dumps(manifest))
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix('.tmp')
    temp.write_bytes(MAGIC + salt + crypt.encrypt(buffer.getvalue()))
    os.replace(temp, output)
    return {'files': len(files), 'bytes': output.stat().st_size}


def unpack(root, bundle, secret):
    if bundle.stat().st_size > LIMIT * 2:
        raise ValueError('恢复包超过大小上限')
    blob = bundle.read_bytes()
    if not blob.startswith(MAGIC):
        raise ValueError('不是加密恢复包')
    salt = blob[len(MAGIC):len(MAGIC) + 16]
    try:
        plain = cipher(secret, salt).decrypt(blob[len(MAGIC) + 16:])
    except InvalidToken as exc:
        raise ValueError('恢复密钥不匹配或文件已损坏') from exc
    with zipfile.ZipFile(io.BytesIO(plain)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or sum(i.file_size for i in archive.infolist()) > LIMIT:
            raise ValueError('恢复包文件重复或超过大小上限')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('version') != 1 or set(names) != set(manifest['files']) | {'manifest.json'}:
            raise ValueError('恢复包清单不匹配')
        # Validate every path and digest before writing any file.
        for name, digest in manifest['files'].items():
            if not allowed(name) or hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise ValueError('恢复包路径或文件校验失败')
        destination = root / 'work/recovered' / uuid.uuid4().hex
        destination.mkdir(parents=True, exist_ok=False)
        for name in manifest['files']:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
        save(destination / 'manifest.json', manifest)
    return destination


class NeedsModel(BaseException):
    """Must not be swallowed by per-article exception handlers."""


def deny_model(*args, **kwargs):
    raise NeedsModel('缓存未命中；恢复模式禁止付费请求')


def original_build_time(snapshot, feed, overview):
    """Use recorded artifact times, never pretend cached evidence is new today."""
    values = [snapshot.get('generatedAt'), (snapshot.get('daily') or {}).get('generatedAt'),
              feed.get('generatedAt'), overview.get('generatedAt')]
    dates = []
    for value in values:
        try:
            date = datetime.fromisoformat(value.replace('Z', '+00:00'))
            dates.append(date if date.tzinfo else date.replace(tzinfo=ZoneInfo('Asia/Shanghai')))
        except (AttributeError, TypeError, ValueError):
            continue
    return max(dates).astimezone(ZoneInfo('Asia/Shanghai')).isoformat() if dates else None


def rebuild(root, source_run):
    """Rebuild overview/funding from exact cached evidence into a new candidate."""
    from .candidate import read
    import tag_news
    import build_company_overview as overview
    import funding_table as funding
    from company_index.inputs import load_articles
    from company_index.extraction import cache_key
    from company_index.output import promote
    from funding.extraction import article_cache_key
    from funding.output import promote_table

    source_run = source_run.resolve()
    recovered = (root / 'work/recovered').resolve()
    if not source_run.is_relative_to(recovered):
        raise ValueError('只接受解密到work/recovered的原运行目录')
    safe_tree(source_run)
    state = read(source_run / 'state.json')
    from .runner import tree_digest
    for rel in ALLOWED:
        accepted = {state.get('recoveryBaseline', {}).get(rel),
                    state.get('recoveryPublishedOutputs', {}).get(rel)} - {None}
        if tree_digest(root / rel, portable=True) not in accepted:
            raise ValueError('正式数据与原运行基线不一致；停止恢复以保留后续更新')
    if any(state.get('stages', {}).get(s, {}).get('status') != 'success' for s in ('news', 'snapshot')):
        raise ValueError('新闻或快照阶段未完成；已保存结果，不能无模型重建后续阶段')
    # New provenance, never edit the old fingerprint or mark its failed stage successful.
    dest = root / 'work/recovery-candidates' / uuid.uuid4().hex
    workspace = dest / 'workspace'
    shutil.copytree(source_run / 'workspace', workspace)
    # Archives omit empty directories; restore required output containers only.
    for rel in (*ALLOWED, 'inputs'):
        (workspace / rel).mkdir(parents=True, exist_ok=True)
    manifest_root = next((p for p in source_run.parents if (p / 'manifest.json').is_file()), None)
    if manifest_root is None:
        raise ValueError('缺少恢复包来源记录')
    raw = manifest_root / 'work/manus/ten-am'
    context = state.get('modelContext') or {}
    if not context.get('LLM_MODEL'):
        raise ValueError('原运行缺少模型标识，禁止猜测缓存版本')
    old_env = {k: os.environ.get(k) for k in ('LLM_MODEL', 'LLM_API_BASE')}
    report = {'sourceRun': str(source_run), 'sourceFingerprint': state['fingerprint'],
              'currentCode': code_digest(root), 'paidCalls': 0, 'published': False,
              'optionalResearch': 'skipped_cache_only', 'missing': {}}
    try:
        for key in old_env:
            os.environ[key] = context.get(key, '')
        tx = tag_news.load_taxonomy(str(root / 'config/taxonomy.json'))
        snapshot, feed = workspace / 'web/public/snapshot.json', workspace / 'data/manus/current.json'
        articles = load_articles(snapshot, feed, raw, tx)
        evidence_path = workspace / 'inputs/company-evidence.json'
        evidence = {a['id']: a for a in read(evidence_path)}
        if set(evidence) != {a['id'] for a in articles}:
            raise ValueError('公司原始证据集合不匹配')
        for a in articles:
            e = evidence[a['id']]
            if e.get('url') != a['url'] or not e.get('content_text'):
                raise ValueError('公司原始证据链接或正文不匹配')
            a['content_text'] = e['content_text']
        caches = read(workspace / 'data/company-overview/extraction_cache.json')
        report['missing']['overview'] = [a['id'] for a in articles
            if caches.get(cache_key(tx, a), {}).get('status') != 'complete']
        fa = funding.load_articles(snapshot, feed, raw, tx)
        fpath = workspace / 'data/funding/extraction_cache.json'
        fc = read(fpath) if fpath.exists() else {}
        report['missing']['funding'] = [a['id'] for a in fa
            if fc.get(article_cache_key(tx, a), {}).get('status') != 'complete']
        if any(report['missing'].values()):
            raise ValueError('存在未缓存的模型结果；缺项已记录，未发起请求')
        private_budget = manifest_root / 'work/company-research-budget'
        recorded_time = original_build_time(read(snapshot), read(feed),
                                            read(workspace / 'data/company-overview/current.json'))
        if (private_budget / 'ledger.json').exists() and not recorded_time:
            raise ValueError('原运行缺少产物时间，禁止把恢复日期写成资料更新时间')
        data = overview.build(snapshot, feed, raw, workspace / 'data/company-overview/current.json',
            workspace / 'data/company-overview', tx, llm_fn=deny_model,
            require_complete=True, allow_partial=True, evidence_path=evidence_path,
            generated_at=recorded_time)
        if (private_budget / 'ledger.json').exists():
            from company_index.daily_research import enrich
            # Isolate the recovered journal from both the live daily lease and
            # the authenticated original checkpoint. Never reset either owner.
            safe_tree(private_budget)
            replay_budget = dest / 'company-research-budget'
            shutil.copytree(private_budget, replay_budget)
            data = enrich(data, tx, dest / 'company-web-research', budget_dir=replay_budget,
                          replay_only=True, read_fn=deny_model, propose_fn=deny_model)
            research = data.get('knownLinkResearch') or {}
            if research.get('budgetUnavailable'):
                raise ValueError('公司资料恢复台账或成功缓存不可用，停止恢复')
            overview.validate(data, tx)
            report['optionalResearch'] = 'replayed_cache_only'
            report['optionalResearchReplay'] = {key: research.get(key, 0)
                for key in ('cacheHits', 'filled', 'failed', 'attempted', 'pagesFetched', 'deferred')}
        promote(data, workspace / 'data/company-overview', workspace / 'web/public')
        table = funding.build_funding_table(snapshot, feed, raw, tx, workspace / 'data/funding',
                                           llm_fn=deny_model, skip_search=True)
        promote_table(table, workspace / 'data/funding', workspace / 'web/public')
        review_dir, summary = prepare(root, workspace)
        report.update(status='review_ready', reviewDirectory=str(review_dir), summary=summary)
        save(review_dir / 'recovery-origin.json', report)
        return report
    except (Exception, NeedsModel):
        report['status'] = 'blocked'
        raise
    finally:
        save(dest / 'recovery-report.json', report)
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('pack', 'unpack', 'rebuild'))
    p.add_argument('--path', type=Path, required=True, help='pack输出文件 / unpack输入文件 / rebuild原运行目录')
    args = p.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    try:
        if args.command == 'rebuild':
            # No network is allowed, including accidental calls introduced later.
            def guard(event, values):
                if event in ('socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
                    raise NeedsModel('恢复模式禁止网络与子进程')
            sys.addaudithook(guard)
            result = rebuild(root, args.path)
        else:
            from llm_common import ensure_env_loaded
            ensure_env_loaded()
            secret = (os.getenv('PIPELINE_RECOVERY_KEY') or os.getenv('PARATERA_API_KEY')
                      or os.getenv('DEEPSEEK_API_KEY') or os.getenv('MANUS_API_KEY'))
            result = (pack(root, args.path, secret) if args.command == 'pack'
                      else {'directory': str(unpack(root, args.path, secret))})
        if os.getenv('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as out:
                for key in ('directory', 'reviewDirectory'):
                    if key in result:
                        out.write(f'{key}={result[key]}\n')
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (Exception, NeedsModel) as exc:
        # Avoid raw network exceptions / signed URLs in Actions logs.
        print('恢复操作未完成：' + (str(exc) if isinstance(exc, (ValueError, NeedsModel))
              else type(exc).__name__), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
