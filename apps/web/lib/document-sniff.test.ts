import { describe, expect, it } from "vitest";

import { sniffDocument } from "./document-sniff";

const bytes = (...values: number[]) => new Uint8Array(values);
const ascii = (text: string) => new TextEncoder().encode(text);

describe("sniffDocument", () => {
  it("recognises PDFs by their header", () => {
    expect(sniffDocument(ascii("%PDF-1.7\n%..."))).toBe("pdf");
  });

  it("recognises the accepted image formats", () => {
    expect(sniffDocument(bytes(0xff, 0xd8, 0xff, 0xe0, 0x00))).toBe("image/jpeg");
    expect(sniffDocument(bytes(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00))).toBe(
      "image/png",
    );
    expect(sniffDocument(ascii("RIFF\u0000\u0000\u0000\u0000WEBPVP8 "))).toBe("image/webp");
  });

  it("refuses anything else, including markup and look-alikes", () => {
    expect(sniffDocument(ascii("<svg xmlns='http://www.w3.org/2000/svg'/>"))).toBe("unsupported");
    expect(sniffDocument(ascii("<html><script>alert(1)</script>"))).toBe("unsupported");
    expect(sniffDocument(ascii("RIFF\u0000\u0000\u0000\u0000WAVEfmt "))).toBe("unsupported");
    expect(sniffDocument(ascii("%PD"))).toBe("unsupported");
    expect(sniffDocument(new Uint8Array())).toBe("unsupported");
  });
});
