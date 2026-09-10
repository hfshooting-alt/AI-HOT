import assert from 'node:assert/strict';
import test from 'node:test';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
const require = createRequire(import.meta.url);
const ts = require('typescript');
for (const extension of ['.tsx', '.ts']) {
  require.extensions[extension] = (module, filename) => module._compile(ts.transpileModule(
    readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } },
  ).outputText, filename);
}
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { CompanyOverviewTable } = require('../../app/_components/company/CompanyOverviewTable.tsx');
const record = { id: 'company:sample', company_name: 'Example', aliases: [], product_names: ['Product'],
  founded: null, country: '印度', business: null, team: null, investors: null, total_funding: null, valuation: null,
  dims: { '行业': 'AI模型', '国家/地区': '其他' }, fieldSources: {},
  sourceArticles: [], firstSeenAt: '2026-09-10', lastSeenAt: '2026-09-10' };
function render(dimSel) {
  return renderToStaticMarkup(React.createElement(CompanyOverviewTable, {
    overview: { generatedAt: '2026-09-10', companies: [record], stats: { companiesTotal: 1, articlesComplete: 1 } },
    dimSel, q: '', onDimChange() {}, onClearSearch() {},
  }));
}
test('zero results retain filter controls, table headings, and recovery action', () => {
  const html = render({ '行业': ['无匹配行业'] });
  assert.match(html, /筛选字段/);
  assert.match(html, /清空筛选与搜索/);
  assert.match(html, /<table/);
  assert.match(html, /成立时间/);
  assert.match(html, /更新日期/);
  assert.match(html, /暂无匹配记录/);
  assert.doesNotMatch(html, /id="company-card-company:sample"/);
});
test('country filter uses the displayed country and table precedes linked cards', () => {
  const html = render({ '国家/地区': ['印度'] });
  assert.doesNotMatch(html, /暂无匹配记录/);
  assert.match(html, /aria-controls="company-card-company:sample"/);
  assert.ok(html.indexOf('</table>') < html.indexOf('id="company-card-company:sample"'));
});
