// Generates docs/GUIDE.md from src/hearthforge/web/guide.js (single source of truth).
import fs from "fs"; import vm from "vm"; import path from "path";
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const src = fs.readFileSync(path.join(root, "src/hearthforge/web/guide.js"), "utf8").replace('"use strict";', "") + "\n;GUIDE";
const guide = vm.runInNewContext(src);
let md = "# Hearthforge guide\n\n> Generated from `src/hearthforge/web/guide.js`: edit that file, then run `node scripts/build_guide_md.mjs`. The same text appears in the app under **Guide**.\n\n";
const list = (steps) => steps.map((s, i) => `${i + 1}. ${s}`).join("\n") + "\n\n";
for (const s of guide) {
  md += `## ${s.title}\n\n`;
  if (s.intro) md += s.intro + "\n\n";
  if (s.steps) md += list(s.steps);
  for (const sub of s.subs || []) md += `### ${sub.title}\n\n` + list(sub.steps);
}
fs.writeFileSync(path.join(root, "docs/GUIDE.md"), md);
console.log("wrote docs/GUIDE.md");
