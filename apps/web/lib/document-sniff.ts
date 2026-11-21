// Identify an uploaded document from its leading bytes, never from its URL or
// filename. Stored keys often have no extension (task documents) and a URL is
// not evidence of content. Only the formats the upload pipeline accepts are
// recognised; anything else is "unsupported" and is never rendered inline.

export type DocumentKind = "pdf" | "image/jpeg" | "image/png" | "image/webp" | "unsupported";

function startsWith(bytes: Uint8Array, signature: readonly number[], offset = 0): boolean {
  if (bytes.length < offset + signature.length) return false;
  return signature.every((value, index) => bytes[offset + index] === value);
}

export function sniffDocument(bytes: Uint8Array): DocumentKind {
  if (startsWith(bytes, [0x25, 0x50, 0x44, 0x46, 0x2d])) return "pdf"; // %PDF-
  if (startsWith(bytes, [0xff, 0xd8, 0xff])) return "image/jpeg";
  if (startsWith(bytes, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) return "image/png";
  if (
    startsWith(bytes, [0x52, 0x49, 0x46, 0x46]) && // RIFF
    startsWith(bytes, [0x57, 0x45, 0x42, 0x50], 8) // WEBP
  ) {
    return "image/webp";
  }
  return "unsupported";
}

/** Upper bound on bytes fetched for an inline view (uploads are capped well below). */
export const MAX_INLINE_DOCUMENT_BYTES = 25 * 1024 * 1024;
