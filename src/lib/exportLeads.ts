import ExcelJS from "exceljs";
import Lead from "@/models/Lead";
import type { Types } from "mongoose";

const LEAD_COLUMNS = [
  "Seller Name",
  "Gig Link",
  "Gig Title",
  "Reviewer Name",
  "Country",
  "Review",
  "Reviewed Image Link",
  "Main Gig Image",
  "Service/Niche",
  "Scraped At",
] as const;

function dedupeLeadsForExport<T extends { gigLink: string; reviewerName: string; review: string }>(
  leads: T[]
): T[] {
  const seen = new Set<string>();
  const out: T[] = [];
  for (const l of leads) {
    const key = [l.gigLink, l.reviewerName, l.review]
      .map((s) => s.trim().toLowerCase())
      .join("|||");
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(l);
  }
  return out;
}

/** Export leads — sheet "Fiverr Leads", full URL text in cells */
export async function buildLeadsExcel(
  filter: { jobId?: Types.ObjectId; userId?: Types.ObjectId }
): Promise<Buffer> {
  const query: Record<string, unknown> = {};
  if (filter.jobId) query.jobId = filter.jobId;
  if (filter.userId) query.userId = filter.userId;

  let leads = await Lead.find(query).sort({ scrapedAt: -1 }).lean();
  leads = dedupeLeadsForExport(leads);

  const workbook = new ExcelJS.Workbook();
  workbook.creator = "FT Solutions - Fiverr Lead Extractor CRM";

  const sheet = workbook.addWorksheet("Fiverr Leads");
  sheet.addRow([...LEAD_COLUMNS]);
  const header = sheet.getRow(1);
  header.font = { bold: true };

  if (leads.length === 0) {
    const row = sheet.addRow(["No real leads extracted."]);
    sheet.mergeCells(row.number, 1, row.number, LEAD_COLUMNS.length);
    row.getCell(1).font = { italic: true };
  }

  for (const l of leads) {
    const row = sheet.addRow([
      l.sellerName || "",
      l.gigLink || "",
      l.gigTitle || "",
      l.reviewerName || "",
      l.country || "",
      l.review || "",
      l.reviewedImageLink || "",
      l.mainGigImage || "",
      l.serviceNiche || "",
      l.scrapedAt ? new Date(l.scrapedAt) : "",
    ]);
    // Full URLs visible (also set as hyperlinks for convenience)
    const urlCols = [2, 7, 8];
    urlCols.forEach((colIdx) => {
      const cell = row.getCell(colIdx);
      const url = String(cell.value || "");
      if (url.startsWith("http")) {
        cell.value = { text: url, hyperlink: url };
      }
    });
  }

  sheet.columns.forEach((col) => {
    col.width = 22;
  });
  sheet.getColumn(2).width = 50;
  sheet.getColumn(6).width = 40;
  sheet.getColumn(7).width = 50;
  sheet.getColumn(8).width = 50;

  const buffer = await workbook.xlsx.writeBuffer();
  return Buffer.from(buffer);
}
