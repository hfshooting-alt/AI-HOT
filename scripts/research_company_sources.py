"""Discover official source leads for existing entities; never publishes data."""
import argparse
import json
from pathlib import Path

import tag_news
from company_index.search import discover
from company_index.output import atomic_write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', action='append', required=True)
    parser.add_argument('--input', default='data/company-overview/current.json')
    parser.add_argument('--output', required=True, help='Private work directory, one process per batch')
    parser.add_argument('--allow-paid', action='store_true')
    parser.add_argument('--max-requests', type=int, default=2)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = (root / args.output).resolve()
    if not output.is_relative_to(root / 'work'):
        parser.error('Search responses must stay in ignored work directory')
    data = json.loads((root / args.input).read_text(encoding='utf-8'))
    rows = data.get('companies', []) + data.get('pendingEntities', [])
    selected = []
    for name in dict.fromkeys(args.name):
        matches = [r for r in rows if r['company_name'] == name]
        if len(matches) != 1:
            parser.error('Entity name missing or ambiguous: ' + name)
        selected.append(matches[0])
    tx = tag_news.load_taxonomy(str(root / 'config/taxonomy.json'))
    results = []
    for row in selected:
        try:
            result = discover(tx, row, output, allow_paid=args.allow_paid, max_requests=args.max_requests)
            results.append(result)
            print(row['company_name'], 'source leads:', len(result['sources']), flush=True)
        except Exception as exc:
            # Do not echo provider errors or credential-bearing request objects.
            results.append({'record_name': row['company_name'], 'status': 'failed', 'errorType': type(exc).__name__})
            print(row['company_name'], type(exc).__name__, flush=True)
            if getattr(exc, 'code', None) in (401, 402, 429):
                break
    atomic_write(output / 'results.json', results)
    return int(any(r['status'] == 'failed' for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
