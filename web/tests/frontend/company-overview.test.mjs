import assert from 'node:assert/strict';
import test from 'node:test';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
const require = createRequire(import.meta.url);
const ts = require('typescript');
for (const extension of ['.tsx', '.ts']) {
  require.extensions[extension] = (module, filename) => module._compile(ts.transpileModule(
    readFileSync(filename, 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } },
  ).outputText, filename);
}
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { CompanyOverviewTable } = require('../../app/_components/company/CompanyOverviewTable.tsx');
const record = { id: 'company:sample', company_name: 'Example', aliases: [], product_names: ['Product'],
  founded: null, country: '印度', business: null, team: null, investors: null, total_funding: null, valuation: null,
  dims: { '行业': 'AI模型', '国家/地区': '其他' }, fieldSources: {},
  sourceArticles: [], firstSeenAt: '2026-09-10', lastSeenAt: '2026-09-10' };

test('foundation type is visible and products use stewardship wording', () => {
  const foundation = { ...record, company_name: 'Tool Foundation', entityType: 'foundation',
    productUpdates: [{ name: 'Product', relationship: 'owned', articleId: 'a' }] };
  const html = renderToStaticMarkup(React.createElement(CompanyOverviewTable, {
    overview: { generatedAt: '2026-09-14', companies: [foundation], stats: { companiesTotal: 1, articlesComplete: 1 } },
    dimSel: {}, q: '', onDimChange() {},
  }));
  assert.match(html, /基金会/);
  assert.match(html, /维护/);
  assert.doesNotMatch(html, /自有/);
});
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

test('unowned products remain visible even without any confirmed companies', () => {
  const html = renderToStaticMarkup(React.createElement(CompanyOverviewTable, {
    overview: { generatedAt: '2026-09-14', companies: [], pendingEntities: [{ ...record,
      company_name: '独立AI产品', sourceArticles: [{id:'news:1',title:'新产品正式发布',url:'https://example.com/product'}] }],
      stats: { companiesTotal: 0, articlesComplete: 1 } },
    dimSel: {}, q: '', onDimChange() {},
  }));
  assert.match(html, /独立AI产品/);
  assert.match(html, /归属待核实/);
  assert.match(html, /https:\/\/example.com\/product/);
  assert.match(html, /不改变新闻分类/);
});

 test("company dates preserve precision and use Arabic numerals", () => {
 const { fmtCompanyDate } = require("../../app/_lib/display/format.ts");
 assert.equal(fmtCompanyDate("一九九三年四月"), "1993-04");
 assert.equal(fmtCompanyDate("1911年6月16日"), "1911-06-16");
 assert.equal(fmtCompanyDate("2022年初"), "2022年初");
 assert.equal(fmtCompanyDate("2016"), "2016年");
 assert.equal(fmtCompanyDate(null), "");
 const { fmtCompanyFounded } = require("../../app/_lib/display/format.ts");
 assert.match(fmtCompanyFounded("2016"), /注册日期待核实/);
 assert.equal(fmtCompanyFounded("1911年6月16日", [{quote: "incorporated on June 16, 1911"}]), "1911-06-16");
 assert.equal(fmtCompanyFounded("2021-06-30", [{value:"2021-06-30",dateBasis:"registration",legalEntity:"X Group Inc."}]), "2021-06-30（X Group Inc.）");
 assert.match(fmtCompanyFounded("2022", [{value:"2021-06-30",dateBasis:"registration"}]), /注册日期待核实/);
});
