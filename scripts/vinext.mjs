// 同一入口支持 Windows / macOS / Linux，保留原有 Wrangler 日志位置。
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const webRoot = fileURLToPath(new URL("../web/", import.meta.url));
const cli = fileURLToPath(new URL("../web/node_modules/vinext/dist/cli.js", import.meta.url));
// 前端工程移入 web 后，仍与 Python/设置服务共用仓库根 .env。
try {
  process.loadEnvFile(fileURLToPath(new URL("../.env", import.meta.url)));
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}
const child = spawn(process.execPath, [cli, ...process.argv.slice(2)], {
  cwd: webRoot,
  stdio: "inherit",
  env: { ...process.env, WRANGLER_LOG_PATH: ".wrangler/wrangler.log" },
});
child.on("error", (error) => {
  console.error(error.message);
  process.exitCode = 1;
});
child.on("exit", (code) => { process.exitCode = code ?? 1; });
