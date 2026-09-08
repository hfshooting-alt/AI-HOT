// source-kind.test.mjs — 来源类型判定与搜索匹配离线单测（node 24 type-stripping 直跑 TS）
// 运行：node tests/frontend/source-kind.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { hostOf, matchItem, sourceKindOf } from "../../app/_lib/display/source.ts";

test("sourceKindOf: 公众号", () => {
  assert.equal(sourceKindOf({ sourceType: "wechat" }), "wechat");
  assert.equal(sourceKindOf({ source: "公众号：游戏葡萄", url: "https://news.qq.com/rain/a/x" }), "wechat");
  assert.equal(sourceKindOf({ source: "Claude：Blog（网页）", url: "https://mp.weixin.qq.com/s?__biz=x" }), "wechat");
  // aihot API 中 source 以「公众号：」开头的条目（build_snapshot 已标 wechat）
  assert.equal(sourceKindOf({ source: "公众号：小红书技术（dots.llm）" }), "wechat");
});

test("sourceKindOf: 推文", () => {
  assert.equal(sourceKindOf({ url: "https://x.com/Alibaba_Qwen/status/2088280182356611304" }), "tweet");
  assert.equal(sourceKindOf({ url: "https://twitter.com/foo/status/1" }), "tweet");
  assert.equal(sourceKindOf({ source: "X：Jensen Huang (@JensenHuang)", url: "https://x.com/foo/1" }), "tweet");
});

test("sourceKindOf: 资讯（媒体域名/名称）", () => {
  assert.equal(sourceKindOf({ url: "https://www.ithome.com/0/991/886.htm" }), "media");
  assert.equal(sourceKindOf({ source: "IT之家（RSS）", url: "https://www.ithome.com/0/990/812.htm" }), "media");
  assert.equal(sourceKindOf({ source: "Hacker News 热门（buzzing.cc 中文翻译）" }), "media");
  assert.equal(sourceKindOf({ source: "Ars Technica：AI（RSS）" }), "media");
  assert.equal(sourceKindOf({ source: "The Decoder：AI News（RSS）" }), "media");
});

test("sourceKindOf: 一手信源（兜底）", () => {
  assert.equal(sourceKindOf({ source: "Claude：Blog（网页）", url: "https://claude.com/blog/x" }), "direct");
  assert.equal(sourceKindOf({ source: "Cursor Blog", url: "https://cursor.com/blog/joining-spacex" }), "direct");
  assert.equal(sourceKindOf({ source: "OpenAI：官网动态（RSS · 排除企业/客户案例）", url: "https://openai.com/index/x" }), "direct");
  assert.equal(sourceKindOf({ source: "Hugging Face：Blog（RSS）", url: "https://huggingface.co/blog/x" }), "direct");
});

test("hostOf: 域名解析", () => {
  assert.equal(hostOf({ url: "https://www.ithome.com/0/1.htm" }), "ithome.com");
  assert.equal(hostOf({ url: "https://x.com/a/1" }), "x.com");
  assert.equal(hostOf({ url: "not a url" }), "");
  assert.equal(hostOf({ permalink: "https://example.com/p" }), "example.com");
});

test("matchItem: 标题/摘要/来源/公众号/URL", () => {
  const item = {
    title: "刚刚，DeepSeek Harness更新！增强多模态",
    summary: "RC.8 版本已经放出，支持多模态。",
    source: "公众号：机器之心",
    mpName: "机器之心",
    url: "https://news.qq.com/rain/a/20260820A05GGM00",
  };
  assert.equal(matchItem(item, "DeepSeek"), true);
  assert.equal(matchItem(item, "RC.8"), true);
  assert.equal(matchItem(item, "机器之心"), true); // 来源名
  assert.equal(matchItem(item, "游戏葡萄"), false);
  assert.equal(matchItem(item, "news.qq.com"), true); // URL
  assert.equal(matchItem(item, ""), true); // 空词不过滤
  assert.equal(matchItem(item, "  "), true);
});

test("matchItem: 公众号名搜索（需求场景）", () => {
  const byMp = { title: "X", source: "公众号：游戏葡萄", mpName: "游戏葡萄" };
  assert.equal(matchItem(byMp, "游戏葡萄"), true);
});
