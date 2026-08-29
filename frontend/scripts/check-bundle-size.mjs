import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const distDir = resolve(frontendDir, "../agi_talent_radar/web/static/dist");
const assetsDir = join(distDir, "assets");
const indexHtml = readFileSync(join(distDir, "index.html"), "utf8");
const entryMatch = indexHtml.match(/<script[^>]+src="[^"]*\/assets\/([^"]+\.js)"/);

if (!entryMatch) throw new Error("无法从 dist/index.html 识别入口 JS。");

const jsAssets = readdirSync(assetsDir)
  .filter((name) => name.endsWith(".js"))
  .map((name) => ({ name, bytes: statSync(join(assetsDir, name)).size }));
const entry = jsAssets.find((asset) => asset.name === entryMatch[1]);

if (!entry) throw new Error(`入口文件不存在：${entryMatch[1]}`);

const limits = {
  entry: 300 * 1024,
  chunk: 500 * 1024,
  total: 1400 * 1024,
};
const total = jsAssets.reduce((sum, asset) => sum + asset.bytes, 0);
const oversized = jsAssets.filter((asset) => asset.bytes > limits.chunk);
const failures = [];

if (entry.bytes > limits.entry) failures.push(`入口 ${(entry.bytes / 1024).toFixed(1)} kB > 300 kB`);
if (oversized.length) failures.push(`超限 chunk：${oversized.map((asset) => `${asset.name} ${(asset.bytes / 1024).toFixed(1)} kB`).join("，")}`);
if (total > limits.total) failures.push(`JS 总量 ${(total / 1024).toFixed(1)} kB > 1400 kB`);

console.log(`入口：${entry.name} ${(entry.bytes / 1024).toFixed(1)} kB`);
console.log(`最大 chunk：${Math.max(...jsAssets.map((asset) => asset.bytes / 1024)).toFixed(1)} kB`);
console.log(`JS 总量：${(total / 1024).toFixed(1)} kB（${jsAssets.length} 个文件）`);

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
