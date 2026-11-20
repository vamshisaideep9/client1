// Agent lead window copy (FR-4.6 as amended 2026-11-14). The Agent sees the
// policy rather than a day-by-day countdown, and a resubmit prompt once the
// lead has expired.

export const AGENT_LEAD_EXPIRY_POLICY =
  "If the customer doesn't respond within 30 days, the lead expires. You can resubmit it after it expires.";

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Unknown date";
  return date.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Kolkata",
  });
}

export function formatAgentLeadExpiry(
  status: string,
  expiresAt: string | null,
  expiredAt: string | null,
  { resubmittable = false, nowMs = Date.now() }: { resubmittable?: boolean; nowMs?: number } = {},
): string {
  if (status === "expired" || expiredAt) {
    const when = expiredAt ? `Expired ${formatDate(expiredAt)}` : "Expired";
    return resubmittable ? `${when} — you can resubmit it` : `${when} — returned to pool`;
  }
  if (status === "converted" || status === "closed") {
    return "No longer subject to expiry";
  }
  if (!expiresAt) return "No expiry deadline";
  if (isAgentLeadExpiryDue(status, expiresAt, expiredAt, nowMs)) {
    return "Expiry due — awaiting pool release";
  }
  return "Active";
}

export function isAgentLeadExpiryDue(
  status: string,
  expiresAt: string | null,
  expiredAt: string | null,
  nowMs: number = Date.now(),
): boolean {
  if (status === "expired" || expiredAt || status === "converted" || status === "closed") {
    return false;
  }
  if (!expiresAt) return false;
  const deadlineMs = new Date(expiresAt).getTime();
  return !Number.isNaN(deadlineMs) && deadlineMs <= nowMs;
}
