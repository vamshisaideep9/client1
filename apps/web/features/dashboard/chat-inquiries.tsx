import type { components } from "@contracts/generated/schema";

import { formatAppliedAt } from "@/features/telecaller/telecaller-requests";

export function ChatInquiries({ inquiries }: {
  inquiries?: components["schemas"]["ChatInquiryRead"][];
}) {
  if (!inquiries?.length) return null;

  return (
    <section aria-label="Website chat inquiries" className="space-y-3 rounded-xl border border-border bg-card p-4">
      <h3 className="font-heading text-sm font-semibold">Website chat inquiries</h3>
      <ul className="grid gap-2">
        {inquiries.map((inquiry) => (
          <li key={inquiry.reference} className="rounded-lg border border-border px-3 py-2">
            <details>
              <summary className="cursor-pointer py-1 text-sm font-medium text-brand-link">
                {inquiry.service} · {inquiry.action}
              </summary>
              <dl className="mt-2 grid gap-2 text-sm">
                <div><dt className="text-text-secondary">Reference</dt><dd className="break-all">{inquiry.reference}</dd></div>
                <div><dt className="text-text-secondary">Submitted</dt><dd><time dateTime={inquiry.created_at}>{formatAppliedAt(inquiry.created_at)}</time></dd></div>
                {inquiry.name && <div><dt className="text-text-secondary">Submitted name</dt><dd className="wrap-anywhere">{inquiry.name}</dd></div>}
                <div><dt className="text-text-secondary">Preferred city or area</dt><dd className="wrap-anywhere">{inquiry.location}</dd></div>
                {Object.entries(inquiry.preferences).map(([question, answer]) =>
                  <div key={question}><dt className="text-text-secondary">{question}</dt><dd>{answer}</dd></div>,
                )}
              </dl>
            </details>
          </li>
        ))}
      </ul>
    </section>
  );
}
