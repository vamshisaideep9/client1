import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only. Documents under review render inside the dashboard:
// PDFs page by page through PDF.js (no embedded content runs), images inline.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

const SUBJECT_ID = "81000000-0000-4000-8000-000000000001";
const LEAD_ID = "82000000-0000-4000-8000-000000000001";

/** A valid two-page PDF that only fills rectangles (no fonts needed). */
function twoPagePdf(): Buffer {
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R >>",
  ];
  const content = "0.1 0.2 0.5 rg 20 20 260 160 re f";
  objects.push(`<< /Length ${content.length} >>\nstream\n${content}\nendstream`);
  objects.push("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R >>");
  let body = "%PDF-1.4\n";
  const offsets: number[] = [];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(body));
    body += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xref = Buffer.byteLength(body);
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  body += offsets.map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("");
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(body, "latin1");
}

const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

async function mockVerification(page: Page, baseURL: string) {
  await mockMobileApi(page, "admin");
  await page.route("**/__e2e__/salary-slip.pdf", (route) =>
    route.fulfill({
      body: twoPagePdf(),
      contentType: "application/pdf",
      headers: { "Content-Disposition": "attachment" },
    }),
  );
  await page.route("**/__e2e__/photo", (route) =>
    route.fulfill({ body: PNG, contentType: "binary/octet-stream" }),
  );
  await page.route("**/api/v1/admin/document-verification/subjects**", (route) =>
    route.fulfill({
      json: {
        subjects: [
          {
            source: "loan_application",
            subject_uuid: SUBJECT_ID,
            lead_uuid: LEAD_ID,
            lead_name: "Asha Rao",
            lead_mobile_masked: "+91 ******3210",
            business_line: "loans",
            subject_label: "Home Loan",
            total_count: 2,
            verified_count: 0,
            latest_upload_at: "2026-11-15T05:00:00Z",
          },
        ],
        total: 1,
      },
    }),
  );
  await page.route("**/api/v1/admin/document-verification/documents?**", (route) =>
    route.fulfill({
      json: {
        documents: [
          {
            source: "loan_application",
            document_id: "83000000-0000-4000-8000-000000000001",
            subject_uuid: SUBJECT_ID,
            doc_type: "salary_slip",
            verified: false,
            review_note: null,
            verified_at: null,
            verified_by_name: null,
            uploaded_at: "2026-11-15T05:00:00Z",
            // No ".pdf" in the key on purpose: the type comes from the bytes.
            download_url: `${baseURL}/__e2e__/salary-slip.pdf`,
          },
          {
            source: "loan_application",
            document_id: "83000000-0000-4000-8000-000000000002",
            subject_uuid: SUBJECT_ID,
            doc_type: "photo",
            verified: false,
            review_note: null,
            verified_at: null,
            verified_by_name: null,
            uploaded_at: "2026-11-15T05:01:00Z",
            download_url: `${baseURL}/__e2e__/photo`,
          },
        ],
      },
    }),
  );
}

for (const viewport of [
  { name: "desktop", width: 1280, height: 900 },
  { name: "mobile", width: 390, height: 844 },
]) {
  test(`document verification shows PDFs and images inside the dashboard (${viewport.name})`, async ({
    page,
    baseURL,
  }, testInfo) => {
    await mockVerification(page, baseURL!);
    await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto("/dashboard/document-verification", { waitUntil: "domcontentloaded" });

    await page.getByText("Asha Rao").first().click();
    const pdfPages = page.getByRole("img", { name: /page \d of 2/ });
    await expect(pdfPages).toHaveCount(2, { timeout: 30_000 });
    const size = await pdfPages.first().evaluate((canvas) => ({
      width: (canvas as HTMLCanvasElement).width,
      height: (canvas as HTMLCanvasElement).height,
    }));
    expect(size.width).toBeGreaterThan(100);
    expect(size.height).toBeGreaterThan(50);

    const photo = page.locator("img[src^='blob:']");
    await expect(photo).toHaveCount(1);
    await expect.poll(() => photo.evaluate((img) => (img as HTMLImageElement).naturalWidth)).toBe(1);
    await page.screenshot({ path: testInfo.outputPath(`document-viewer-${viewport.name}.png`), fullPage: false });
  });
}
