# AI HOT User Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create and publish a concise Chinese `USER_GUIDE.md` for ordinary AI HOT readers, with a short Windows local-use appendix.

**Architecture:** Add one standalone Markdown file at the repository root. Derive every label and behavior from the current React components, keep operating details out of the main reading flow, and verify content plus the existing test suite before pushing.

**Tech Stack:** Markdown, Windows PowerShell, Git, Python pytest, Node.js test runner.

---

### Task 1: Create the user guide

**Files:**
- Create: `USER_GUIDE.md`
- Reference: `app/_components/Sidebar.tsx`
- Reference: `app/_components/SearchToolbar.tsx`
- Reference: `app/_components/views/HotView.tsx`
- Reference: `app/_components/views/DailyReportView.tsx`
- Reference: `app/_components/views/SettingsView.tsx`
- Reference: `app/_components/FundingTableView.tsx`

- [ ] **Step 1: Add the title, quick access, and reading path**

Create `USER_GUIDE.md` with the title `# AI HOT 使用说明`, the CloudBase URL, a one-paragraph product description, and a short “第一次使用” sequence: open the site, choose a view, use filters, then open the original article.

- [ ] **Step 2: Document the five views with current labels**

Use the exact navigation labels `精选`、`全部 AI 动态`、`热点榜`、`AI 日报`、`设置`. Explain that AI 日报 contains `日报` and `周报`, and that the hotspot heat number expands its source list.

- [ ] **Step 3: Document search, categories, tags, and source filters**

List the six categories exactly: `融资动态`、`深度访谈`、`产品和模型发布`、`论文研究`、`大厂动态`、`泛行业新闻`. State that search covers title, summary, source, account name, and URL; source filters are `一手信源`、`资讯`、`推文`、`公众号`.

- [ ] **Step 4: Explain financing rows and source verification**

Explain horizontal scrolling, the sticky company column, source links, and the `搜` badge for fields completed by online search. Remind readers that AI-extracted fields and summaries should be checked against original sources.

- [ ] **Step 5: Add data notes, troubleshooting, and local appendix**

State that times use Asia/Shanghai, live API failure falls back to snapshot data, and static data may lag. Cover empty search results, offline settings service, and stale data. Add Windows commands:

```powershell
npm install
$env:WRANGLER_LOG_PATH='.wrangler/wrangler.log'
npx vinext dev
```

In a second terminal:

```powershell
node scripts/settings-server.mjs
```

Explain that the settings page writes the repository-root `.env`, public deployments cannot write local files, and `.env` must never be committed.

### Task 2: Review and verify the guide

**Files:**
- Review: `USER_GUIDE.md`
- Test: `tests/`

- [ ] **Step 1: Check required content**

Run:

```powershell
rg -n "精选|全部 AI 动态|热点榜|AI 日报|设置|融资动态|一手信源|公众号|USER_GUIDE|CloudBase|\.env" USER_GUIDE.md
```

Expected: each required topic appears in the guide.

- [ ] **Step 2: Scan for placeholders, restricted phrasing, and secret-like strings**

Run:

```powershell
rg -n "T[B]D|TO[D]O|不[是].*而[是]|sk-[A-Za-z0-9]{12,}|tvly-[A-Za-z0-9]{12,}" USER_GUIDE.md
```

Expected: exit code 1 with no matches.

- [ ] **Step 3: Run the Python suite**

Run:

```powershell
python -m pytest tests/ -q
```

Expected: `169 passed`; the known `.pytest_cache` permission warning is acceptable.

- [ ] **Step 4: Run the Node suites**

Run:

```powershell
node tests/rendered-html.test.mjs
node tests/source-kind.test.mjs
node tests/test_settings_server.mjs
```

Expected: 2 + 7 + 9 tests pass with zero failures.

### Task 3: Commit and publish

**Files:**
- Commit: `USER_GUIDE.md`

- [ ] **Step 1: Inspect the change scope**

Run `git status --short` and `git diff --check`. Confirm `scripts/manus_source/runner.py` and existing diagnostic files remain outside the staged change.

- [ ] **Step 2: Commit only the guide**

```powershell
git add -- USER_GUIDE.md
git commit -m "docs: 新增用户使用说明"
```

- [ ] **Step 3: Recheck the remote and push**

Run `git fetch origin`, confirm `origin/main` has no remote-only commit, then run `git push origin main`.

- [ ] **Step 4: Verify the remote hash**

Run `git ls-remote origin refs/heads/main` and compare it with `git rev-parse HEAD`. Expected: the hashes are identical.
