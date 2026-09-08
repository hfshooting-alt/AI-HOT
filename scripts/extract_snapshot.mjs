// 一次性工具：从现有 public/index.html 提取内嵌 DATA，生成 public/snapshot.json
// 与 build_snapshot.py 的 --snapshot-json 产物同源同构（用于本地预览，CI 由脚本生成）
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url))); // 仓库根目录（scripts/ 的上一级）
const html = readFileSync(join(root, "web/public/index.html"), "utf-8");
const m = html.match(/const DATA = (\{[\s\S]*?\});\r?\nconst SECTION_COLORS/);
if (!m) {
  console.error("未找到 DATA 内嵌数据");
  process.exit(1);
}
JSON.parse(m[1]); // 校验 JSON 合法性
writeFileSync(join(root, "web/public/snapshot.json"), m[1], "utf-8");
console.log("public/snapshot.json 已生成，大小", m[1].length);
