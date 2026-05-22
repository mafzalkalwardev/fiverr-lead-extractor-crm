/** Which backend processes scrape jobs. Default: Python (MongoDB poll). */

export type ScraperEngine = "python" | "node";

export function getScraperEngine(): ScraperEngine {
  const v = (process.env.SCRAPER_ENGINE || "python").toLowerCase();
  return v === "node" ? "node" : "python";
}

export function isPythonScraperEngine(): boolean {
  return getScraperEngine() === "python";
}

export function isNodeScraperEngine(): boolean {
  return getScraperEngine() === "node";
}
