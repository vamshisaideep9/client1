import { describe, expect, it } from "vitest";
import ExcelJS from "exceljs";
import { LEAD_SHEET_HEADERS, leadRowsFromCells, leadSheetCsv, parseCsv, readLeadSheet, safeCsvCell } from "./agent-lead-sheet";

describe("Agent lead spreadsheets", () => {
  it("reads BOM, quoted commas, quotes and multiline descriptions without shifting fields", () => {
    const csv = '\uFEFFSNO,Name,Mobile Number,Email,Requirement,Description\r\n1,"Asha, V",9812345678,,Home loan,"Call ""later""\nplease"';
    expect(leadRowsFromCells(parseCsv(csv))).toEqual([{
      sno: "1", name: "Asha, V", mobile: "9812345678", email: null,
      requirement: "Home loan", description: 'Call "later"\nplease',
    }]);
    expect(() => parseCsv('1,"unfinished')).toThrow("not closed");
  });
  it("refuses unknown headers, empty sheets, extra columns and more than 200 rows", () => {
    expect(() => leadRowsFromCells([["SNO", "password"]])).toThrow("headers");
    expect(() => leadRowsFromCells([LEAD_SHEET_HEADERS])).toThrow("1 and 200");
    expect(() => leadRowsFromCells([LEAD_SHEET_HEADERS, ["1", "A", "9812345678", "", "", "", "extra"]])).toThrow("extra columns");
    expect(() => leadRowsFromCells([LEAD_SHEET_HEADERS, ...Array.from({ length: 201 }, () => ["1", "A", "9812345678"])] )).toThrow("1 and 200");
    expect(() => leadRowsFromCells([LEAD_SHEET_HEADERS, ["1", "A".repeat(501)]] )).toThrow("too long");
  });
  it("neutralises executable CSV cells, including leading controls, and quotes embedded delimiters", () => {
    for (const value of ["=HYPERLINK(1)", "+cmd", "-cmd", "@SUM(1)", "  =1", "\t=1", "\u0000=1"]) {
      expect(safeCsvCell(value).startsWith("\"'")).toBe(true);
    }
    expect(safeCsvCell('A,"B"')).toBe('"A,""B"""');
    expect(leadSheetCsv([["=1", "Plain"]])).toBe('\uFEFF"\'=1","Plain"');
  });
  it("reads numeric Excel mobile cells as plain text and rejects formula cells", async () => {
    const workbook = new ExcelJS.Workbook();
    const sheet = workbook.addWorksheet("Leads");
    sheet.addRow([...LEAD_SHEET_HEADERS]);
    sheet.addRow([1, "Asha", 9812345678, "", "Home Loan", "Call later"]);
    const bytes = await workbook.xlsx.writeBuffer();
    const file = new File([bytes as unknown as ArrayBuffer], "leads.xlsx");
    expect((await readLeadSheet(file))[0].mobile).toBe("9812345678");
    sheet.getCell("B2").value = { formula: 'HYPERLINK("bad")', result: "Asha" };
    const formula = new File([await workbook.xlsx.writeBuffer() as unknown as ArrayBuffer], "leads.xlsx");
    await expect(readLeadSheet(formula)).rejects.toThrow("plain values");
    await expect(readLeadSheet(new File(["bad"], "leads.xlsx"))).rejects.toThrow("supported XLSX");
  });
});
