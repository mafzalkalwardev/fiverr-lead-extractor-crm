import "@/lib/load-env";
import { normalizeFiverrUrl } from "@/scraper/fiverr/urls";

const NICHE = process.argv[2] || "car wrap";

async function tryFetch(label: string, url: string) {
  const res = await fetch(url, {
    headers: {
      "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    },
    signal: AbortSignal.timeout(20_000),
  });
  const html = await res.text();
  const found = new Set<string>();
  const re = /https?:\/\/www\.fiverr\.com\/[a-z0-9_-]+\/[a-z0-9_-]+/gi;
  let m;
  while ((m = re.exec(html)) !== null) {
    const n = normalizeFiverrUrl(m[0]);
    if (n) found.add(n);
  }
  console.log(`${label}: status=${res.status} len=${html.length} urls=${found.size}`);
  [...found].slice(0, 8).forEach((u) => console.log(" ", u));
  return [...found];
}

async function main() {
  const q = encodeURIComponent(`site:fiverr.com ${NICHE}`);
  const all = new Set<string>();
  for (const [label, url] of [
    ["google", `https://www.google.com/search?q=${q}&num=20`],
    ["startpage", `https://www.startpage.com/sp/search?q=${q}`],
    ["ecosia", `https://www.ecosia.org/search?q=${q}`],
  ] as const) {
    try {
      const urls = await tryFetch(label, url);
      urls.forEach((u) => all.add(u));
    } catch (e) {
      console.log(`${label}: error`, e);
    }
  }
  console.log("\nTotal unique:", all.size);
  process.exit(all.size > 0 ? 0 : 1);
}

main();
