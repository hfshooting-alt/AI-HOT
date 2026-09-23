// 新闻搜索离线单测；文件名保留现有 package 脚本兼容。
import { test } from "node:test";
import assert from "node:assert/strict";
import { matchItem } from "../../app/_lib/display/source.ts";

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
