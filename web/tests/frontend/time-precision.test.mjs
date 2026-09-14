import assert from 'node:assert/strict';
import test from 'node:test';
import { fmtItemTime } from '../../app/_lib/display/format.ts';

test('date-only yesterday never displays an invented clock time', () => {
  const text = fmtItemTime({ id: 'a', title: 'A', publishedAt: '2026-09-13', publishedPrecision: 'date',
    timeEvidence: { originalText: '昨天', observedAt: '2026-09-14T10:00:00+08:00' } });
  assert.match(text, /2026-09-13.*原文标注昨天.*具体时刻未披露/);
  assert.doesNotMatch(text, /00:00|12:00/);
});

test('relative timestamps remain visibly estimated after publication', () => {
  const text = fmtItemTime({ id: 'a', title: 'A', publishedAt: '2026-09-14T05:00:00+08:00', publishedPrecision: 'relative',
    timeEvidence: { originalText: '5小时前', observedAt: '2026-09-14T10:00:00+08:00' } });
  assert.match(text, /采集时标注5小时前（估算）/);
  assert.doesNotMatch(text, /05:00/);
});
