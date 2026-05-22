import { normalizeFiverrUrl } from "../fiverr/urls";

const INSTANCES = [
  "https://searx.be",
  "https://search.bus-hit.me",
  "https://opensearch.sethforprivacy.com",
];

/** Discover gigs via public SearX instances (JSON API) */
export async function discoverGigsViaSearx(
  niche: string,
  maxGigs: number
): Promise<string[]> {
  const query = `site:fiverr.com ${niche} "I will"`;
  const seen = new Set<string>();
  const results: string[] = [];

  for (const base of INSTANCES) {
    try {
      const url = `${base}/search?q=${encodeURIComponent(query)}&format=json`;
      console.log(`[discovery] SearX: ${base}`);
      const res = await fetch(url, {
        headers: { Accept: "application/json", "User-Agent": "Mozilla/5.0" },
        signal: AbortSignal.timeout(15_000),
      });
      if (!res.ok) continue;
      const data = (await res.json()) as { results?: { url?: string }[] };
      for (const r of data.results || []) {
        const full = normalizeFiverrUrl(r.url || "");
        if (!full || seen.has(full)) continue;
        seen.add(full);
        results.push(full);
        if (results.length >= maxGigs) return results;
      }
      if (results.length > 0) return results;
    } catch (err) {
      console.warn(`[discovery] SearX ${base} failed:`, err);
    }
  }

  console.log(`[discovery] SearX total: ${results.length}`);
  return results;
}
