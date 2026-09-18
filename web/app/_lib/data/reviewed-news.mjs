/** Merge explicitly reviewed supplements without changing scheduled-batch metadata.
 * A later scheduled window retires the supplement from the current news view.
 * @param {import('../domain/types').NewsItem[]} base
 * @param {any} data
 * @param {string | undefined} batchEnd
 * @returns {import('../domain/types').NewsItem[]}
 */
export function mergeReviewedNews(base, data, batchEnd) {
  if (data?.schemaVersion !== 1 || !Array.isArray(data.entries)) return base;
  const out = [...base];
  for (const entry of data.entries) {
    const item = entry?.item;
    const start = Date.parse(entry?.collectionWindow?.start);
    const end = Date.parse(entry?.collectionWindow?.end);
    const published = Date.parse(item?.publishedAt);
    if (entry?.reviewed !== true || !Number.isFinite(Date.parse(entry.reviewedAt))
      || !Number.isFinite(start) || !Number.isFinite(end) || end <= start
      || !Number.isFinite(published) || published < start || published >= end
      || (batchEnd && Date.parse(batchEnd) > end)
      || !item?.id || !item?.title || !item?.summary
      || !/^https:\/\//.test(item.url || '') || item.classification?.autoFallback !== false) continue;
    if (out.some(previous => previous.id === item.id || previous.url === item.url
      || previous.title.trim().toLowerCase() === item.title.trim().toLowerCase())) continue;
    out.push(item);
  }
  return out.sort((a, b) => Date.parse(b.publishedAt) - Date.parse(a.publishedAt));
}

/** Company supplements remain as historical evidence after news leaves the current window.
 * @param {any} overview
 * @param {any} data
 */
export function mergeReviewedCompanies(overview, data) {
  if (!overview || data?.schemaVersion !== 1 || !Array.isArray(data.entries)) return overview;
  const result = structuredClone(overview);
  const union = (a, b, key) => [...new Map([...a, ...b].map(value => [key(value), value])).values()];
  const productKey = name => name.replace(/\s+/g, '').toLowerCase();
  for (const entry of data.entries) {
    if (entry?.reviewed !== true || !Number.isFinite(Date.parse(entry.reviewedAt))) continue;
    if (!Array.isArray(entry.companies)) continue;
    if (Date.parse(entry.reviewedAt) > Date.parse(result.generatedAt || '')) result.generatedAt = entry.reviewedAt;
    for (const company of entry.companies) {
      if (!company.id || !company.company_name || !company.sourceArticles?.some(a => a.id === entry.item?.id)) continue;
      const aliases = new Set([company.company_name, ...(company.aliases || [])]);
      const old = result.companies.find(row => row.id === company.id || aliases.has(row.company_name));
      if (!old) { result.companies.push(structuredClone(company)); continue; }
      // Preserve newer normal-pipeline fields. Add only missing profile facts and source evidence.
      old.id = company.id;
      old.company_name = company.company_name;
      old.aliases = [...new Set([...(old.aliases || []), ...(company.aliases || [])])];
      for (const key of ['business','country','founded','team','investors','total_funding','valuation']) {
        if (!old[key] && company[key]) {
          old[key] = company[key];
          if (key === 'country' && company.dims?.['国家/地区']) old.dims = {...old.dims,'国家/地区':company.dims['国家/地区']};
        }
      }
      old.sourceArticles = union(company.sourceArticles || [],old.sourceArticles || [],row => row.id)
        .sort((a,b) => Date.parse(b.publishedAt)-Date.parse(a.publishedAt));
      // Names approved for the table are authoritative. Legacy evidence can
      // contain a removed brand or differently cased spelling of the same model.
      const productNames = new Map([...(company.product_names || []), ...(old.product_names || [])]
        .map(name => [productKey(name), name]));
      old.productUpdates = union(company.productUpdates || [],old.productUpdates || [],row => `${row.articleId}|${productKey(row.name)}`)
        .filter(row => productNames.has(productKey(row.name)))
        .sort((a,b) => Date.parse(b.publishedAt)-Date.parse(a.publishedAt));
      old.product_names = [...new Set([...old.productUpdates.map(row=>productNames.get(productKey(row.name))), ...productNames.values()])];
      old.fieldSources ||= {};
      for (const [field, evidence] of Object.entries(company.fieldSources || {})) {
        old.fieldSources[field] = union(evidence,old.fieldSources[field] || [],row => JSON.stringify(row));
      }
      if (Date.parse(company.lastSeenAt) > Date.parse(old.lastSeenAt)) {
        old.lastSeenAt = company.lastSeenAt;
        old.latestReportAt = company.latestReportAt;
        old.updatedAt = company.updatedAt;
      }
      if (!old.profileUpdatedAt || Date.parse(company.profileUpdatedAt) > Date.parse(old.profileUpdatedAt)) old.profileUpdatedAt = company.profileUpdatedAt;
    }
  }
  result.companies.sort((a,b) => Date.parse(b.latestReportAt || b.lastSeenAt)-Date.parse(a.latestReportAt || a.lastSeenAt));
  result.stats.companiesTotal = result.companies.length;
  result.stats.productsTotal = result.companies.reduce((n,c) => n+c.product_names.length,0);
  result.reviewedSupplements = data.entries.filter(e=>e.reviewed===true).map(e=>({articleId:e.item.id,reviewedAt:e.reviewedAt}));
  return result;
}
