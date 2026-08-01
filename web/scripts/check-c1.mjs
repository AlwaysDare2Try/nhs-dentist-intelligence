import { readFileSync } from "node:fs";
import * as lib from "../app/lib/practices.js";
const raw = JSON.parse(readFileSync("public/data/practices.json", "utf8"));
const practices = lib.zip(raw);
console.log(`loaded ${practices.length.toLocaleString()} practices`);

const found = lib.nearest(practices, 51.50101, -0.141563, 8);
console.log(`\nnearest 8 to SW1A 1AA (Westminster):`);
for (const p of found) {
  const t = lib.trust(p);
  console.log(`  ${p.km.toFixed(2)} km  ${(p.name||p.id).slice(0,32).padEnd(32)} [${t.label}]`);
  console.log(`           ${lib.describe(p)}`);
}
console.log(`\naccepting in that set: ${found.filter(p => p.status==="accepting").length}/8`);

const bad = practices.filter(p => {
  const d = lib.describe(p).toLowerCase();
  return d.includes("currently") || d.includes("is accepting") || d.includes("does accept");
});
console.log(`\nC1 check — descriptions asserting current fact: ${bad.length}`);
const accNoDate = practices.filter(p => p.status === "accepting" && !p.confirmed);
console.log(`accepting practices lacking a confirmed date: ${accNoDate.length}`);
const noCoord = practices.filter(p => p.lat == null).length;
console.log(`practices without coordinates (excluded from search): ${noCoord}`);
