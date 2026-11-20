export function ResubmissionBadge({ count, at }: { count: number; at?: string | null }) {
  if (!count) return null;
  return (
    <span className="mt-1 inline-flex rounded-full bg-brand-cta-tint px-2.5 py-0.5 text-xs font-medium text-brand-link"
      title={at ? `Last resubmitted ${new Date(at).toLocaleString("en-IN")}` : undefined}>
      Resubmitted ×{count}
    </span>
  );
}
