"""Show processing degradation separately from the GitHub job conclusion."""
import json
import os
from pathlib import Path

from .runner import tree_digest


def render(root):
    lines = ['### AI HOT：运行与发布结果', '',
             '作业完成不等于所有信源或处理阶段成功。', '']
    states = sorted((root / 'work/runs').glob('*/ten-am/*/state.json'))
    if not states:
        return '\n'.join(lines + ['没有本轮阶段记录；请检查初始化或 dry-run 日志。', ''])
    for path in states:
        state = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(state, dict) or not isinstance(state.get('stages'), dict):
            lines.extend(['阶段记录格式不完整；结果未知，请检查状态 Artifact。', ''])
            continue
        stages = state['stages']
        failures = {name: row for name, row in stages.items()
                    if isinstance(row, dict) and row.get('status') == 'failed'}
        lines.append('存在失败阶段，成功来源可按既定规则发布。' if failures
                     else '阶段记录未记载失败；unknown 不代表通过，来源覆盖仍需单独核验。')
        lines.extend(['', '| 阶段 | 状态 | 退出码 |', '| --- | --- | --- |'])
        for name in ('aihot', 'discovery', 'content', 'news', 'snapshot', 'overview', 'funding'):
            row = stages.get(name)
            row = row if isinstance(row, dict) else {}
            status = row.get('status')
            status = status if status in ('success', 'failed', 'running', 'pending', 'skipped') else 'unknown'
            code = row.get('exitCode')
            lines.append(f'| {name} | {status} | {code if type(code) is int else "—"} |')
        lines.extend(['', f'本地数据晋升：{"完成" if state.get("published") is True else "未确认"}。'])
        snapshot_path = root / 'web/public/snapshot.json'
        outputs = state.get('publishedOutputs')
        expected = outputs.get('web/public') if isinstance(outputs, dict) else None
        if state.get('published') is True and snapshot_path.exists() and expected and expected == tree_digest(root / 'web/public'):
            snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
            if state.get('collectionWindow') and snapshot.get('collectionWindow') == state['collectionWindow']:
                status = snapshot.get('collectionStatus', {})
                counts = {name: 0 for name in ('AIHOT', 'Manus')}
                for item in snapshot.get('all', {}).get('items', []):
                    prefix = str(item.get('id', '')).split(':', 1)[0]
                    if prefix in ('aihot', 'manus'):
                        counts['AIHOT' if prefix == 'aihot' else 'Manus'] += 1
                lines.append(f'本批新闻：AIHOT {counts["AIHOT"]} 条；Manus {counts["Manus"]} 条。')
                if status.get('degraded') is True:
                    lines.append('来源覆盖不完整；不得将本批标为全信源通过。')
        lines.extend(['Git 推送及 Pages 部署请核对发布回执与独立部署作业。', ''])
    return '\n'.join(lines)


if __name__ == '__main__':
    # Reporting must never hide or change the collection/deployment outcome.
    try:
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as stream:
            stream.write(render(Path.cwd()))
    except Exception:
        print('::warning::运行摘要不可用；请检查阶段状态与发布回执。')
