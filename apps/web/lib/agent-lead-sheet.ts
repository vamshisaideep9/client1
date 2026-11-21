import type { AgentLeadBulkRow } from "@/lib/agent-api";

export const LEAD_SHEET_HEADERS = ["SNO", "Name", "Mobile Number", "Email", "Requirement", "Description"] as const;
export const LEAD_SHEET_MAX_BYTES = 5 * 1024 * 1024;
const KEYS = ["sno", "name", "mobile", "email", "requirement", "description"] as const;
const CAPS = [40, 500, 40, 320, 200, 4000];

/** CSV quoting is separate from formula neutralisation, which quoting alone cannot provide. */
export function safeCsvCell(value: unknown): string {
  let text = String(value ?? "");
  if (/^[\s\x00-\x20]*[=+@-]/.test(text) || /^[\t\r\n]/.test(text)) text = "'" + text;
  return '"' + text.replaceAll('"', '""') + '"';
}
export function leadSheetCsv(rows: readonly (readonly unknown[])[]): string {
  return "\uFEFF" + rows.map((row) => row.map(safeCsvCell).join(",")).join("\r\n");
}

export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [], cell = "", quoted = false, endedQuote = false;
  text = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (char === '"') { quoted = false; endedQuote = true; }
      else cell += char;
    } else if (char === '"' && cell === "" && !endedQuote) quoted = true;
    else if (char === ",") { row.push(cell); cell = ""; endedQuote = false; }
    else if (char === "\r" || char === "\n") {
      row.push(cell); rows.push(row); row = []; cell = ""; endedQuote = false;
      if (char === "\r" && text[i + 1] === "\n") i++;
    } else {
      if (endedQuote || char === '"') throw new Error("The CSV has an invalid quoted cell.");
      cell += char;
    }
    if (rows.length > 202 || cell.length > 5000 || row.length > 6) throw new Error("Use the six-column template with at most 200 rows.");
  }
  if (quoted) throw new Error("A CSV quoted cell is not closed.");
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

export function leadRowsFromCells(cells: readonly (readonly unknown[])[]): AgentLeadBulkRow[] {
  const nonempty = cells.filter((row) => row.some((value) => String(value ?? "").trim() !== ""));
  const header = nonempty[0]?.map((value) => String(value ?? "").trim().toLowerCase());
  if (!header || header.length !== 6 || header.some((value, i) => value !== LEAD_SHEET_HEADERS[i].toLowerCase())) {
    throw new Error("Use the template headers: SNO, Name, Mobile Number, Email, Requirement, Description.");
  }
  const records = nonempty.slice(1);
  if (records.length < 1 || records.length > 200) throw new Error("Add between 1 and 200 lead rows.");
  return records.map((values, rowIndex) => {
    if (values.length > 6) throw new Error(`Row ${rowIndex + 2} has extra columns.`);
    const row: AgentLeadBulkRow = {};
    KEYS.forEach((key, index) => {
      const text = String(values[index] ?? "").trim();
      if (text.length > CAPS[index]) throw new Error(`Row ${rowIndex + 2}: ${LEAD_SHEET_HEADERS[index]} is too long.`);
      row[key] = text || null;
    });
    return row;
  });
}

// Check declared expanded ZIP sizes before ExcelJS inflates a local workbook.
function checkWorkbookArchive(buffer: ArrayBuffer): void {
  const view = new DataView(buffer);
  let expanded = 0, entries = 0;
  for (let offset = 0; offset + 46 <= view.byteLength; offset++) {
    if (view.getUint32(offset, true) !== 0x02014b50) continue;
    const size = view.getUint32(offset + 24, true);
    if ((view.getUint16(offset + 8, true) & 1) || size === 0xffffffff) throw new Error("Encrypted and ZIP64 workbooks are not supported.");
    expanded += size; entries++;
    if (expanded > 20 * 1024 * 1024 || entries > 500) throw new Error("This workbook is too large. Use a smaller template file.");
    offset += 45 + view.getUint16(offset + 28, true) + view.getUint16(offset + 30, true) + view.getUint16(offset + 32, true);
  }
  if (!entries) throw new Error("This is not a supported XLSX workbook.");
}

export async function readLeadSheet(file: File): Promise<AgentLeadBulkRow[]> {
  if (file.size > LEAD_SHEET_MAX_BYTES) throw new Error("Choose a file no larger than 5 MB.");
  if (/\.csv$/i.test(file.name)) return leadRowsFromCells(parseCsv(await file.text()));
  if (!/\.xlsx$/i.test(file.name)) throw new Error("Choose a .csv or .xlsx template file.");
  const buffer = await file.arrayBuffer();
  checkWorkbookArchive(buffer);
  const { default: ExcelJS } = await import("exceljs");
  const workbook = new ExcelJS.Workbook();
  try { await workbook.xlsx.load(buffer); }
  catch { throw new Error("Could not read this workbook. Save a new .xlsx copy and try again."); }
  const sheet = workbook.worksheets[0];
  if (!sheet || sheet.actualRowCount > 201 || sheet.actualColumnCount > 6) throw new Error("Use the six-column template with at most 200 rows.");
  const cells: string[][] = [];
  sheet.eachRow((row) => {
    const values: string[] = [];
    row.eachCell({ includeEmpty: true }, (cell, column) => {
      if (cell.type === ExcelJS.ValueType.Formula) throw new Error("Replace spreadsheet formulas with plain values before uploading.");
      values[column - 1] = cell.text;
    });
    cells.push(values);
  });
  return leadRowsFromCells(cells);
}

export async function leadSheetTemplate(): Promise<ArrayBuffer> {
  const { default: ExcelJS } = await import("exceljs");
  const workbook = new ExcelJS.Workbook();
  const sheet = workbook.addWorksheet("Agent leads");
  sheet.addRow([...LEAD_SHEET_HEADERS]);
  sheet.getRow(1).font = { bold: true };
  LEAD_SHEET_HEADERS.forEach((_, index) => { sheet.getColumn(index + 1).width = index === 5 ? 45 : 24; sheet.getColumn(index + 1).numFmt = "@"; });
  return await workbook.xlsx.writeBuffer() as ArrayBuffer;
}

export function downloadLeadSheet(content: BlobPart, name: string, type: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = name; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
