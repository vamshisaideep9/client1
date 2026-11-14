"use client";

import { Badge } from "@/components/ui/badge";
import { DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { FormAnswerSummary } from "@/features/loans/form-answer-summary";
import { LoanProgressForm } from "@/features/loans/loan-progress-form";
import type { ApiResponse } from "@/lib/api/client";
import { formatINR } from "@/lib/format";
import type {
  LoanApplicationProgressUpdate,
  LoanTxnCreate,
  TelecallerLoanApplication,
} from "@/lib/telecaller-api";

import { AddTxnDialog } from "./telecaller-add-txn-dialog";

const STATUS_LABEL: Record<string, string> = {
  new: "New",
  assigned: "Assigned",
  contacted: "Contacted",
  docs_collected: "Docs collected",
  submitted_to_bank: "Submitted to bank",
  sanctioned: "Sanctioned",
  disbursed: "Disbursed",
  closed: "Closed",
  rejected: "Rejected",
  on_hold: "On hold",
};

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function TransactionHistory({ application }: { application: TelecallerLoanApplication }) {
  if (application.txns.length === 0) {
    return <p className="text-sm text-text-secondary">No transactions entered yet.</p>;
  }

  return (
    <>
      {/* Phones: one card per entry instead of a sideways-scrolling table. */}
      <ul className="space-y-2 sm:hidden">
        {application.txns.map((txn) => (
          <li key={txn.id} className="rounded-lg border border-border p-3">
            <div className="flex items-baseline justify-between gap-3">
              <span className="min-w-0 break-words font-medium text-text-primary">
                {txn.bank_name ?? "Not recorded"}
              </span>
              <span className="shrink-0 text-xs text-text-secondary">{formatDate(txn.txn_date)}</span>
            </div>
            <dl className="mt-2 grid grid-cols-2 gap-2 text-sm">
              <div>
                <dt className="text-xs text-text-secondary">Amount</dt>
                <dd className="tabular-nums text-text-primary">
                  {txn.amount != null ? formatINR(Number(txn.amount)) : "—"}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-text-secondary">Interest</dt>
                <dd className="tabular-nums text-text-primary">
                  {txn.interest_rate != null ? `${Number(txn.interest_rate)}%` : "—"}
                </dd>
              </div>
            </dl>
          </li>
        ))}
      </ul>
      <div className="hidden overflow-x-auto rounded-lg border border-border sm:block">
        <table className="w-full text-left text-sm">
          <thead className="bg-muted/50 text-xs uppercase tracking-wide text-text-secondary">
            <tr>
              <th scope="col" className="px-3 py-2.5 font-medium">Bank</th>
              <th scope="col" className="px-3 py-2.5 font-medium">Amount</th>
              <th scope="col" className="px-3 py-2.5 font-medium">Interest</th>
              <th scope="col" className="px-3 py-2.5 font-medium">Date</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {application.txns.map((txn) => (
              <tr key={txn.id}>
                <td className="px-3 py-3 font-medium text-text-primary">
                  {txn.bank_name ?? "Not recorded"}
                </td>
                <td className="px-3 py-3 tabular-nums text-text-primary">
                  {txn.amount != null ? formatINR(Number(txn.amount)) : "—"}
                </td>
                <td className="px-3 py-3 tabular-nums text-text-primary">
                  {txn.interest_rate != null ? `${Number(txn.interest_rate)}%` : "—"}
                </td>
                <td className="px-3 py-3 text-text-secondary">{formatDate(txn.txn_date)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function TelecallerLoanAppsSection({
  applications,
  onAddTxn,
  onUpdateApp,
}: {
  applications: TelecallerLoanApplication[];
  onAddTxn: (applicationId: string, payload: LoanTxnCreate) => Promise<ApiResponse<unknown>>;
  onUpdateApp: (
    applicationId: string,
    payload: LoanApplicationProgressUpdate,
  ) => Promise<ApiResponse<unknown>>;
}) {
  if (applications.length === 0) {
    return (
      <DashboardPanel
        title="Loan application"
        description="Application details and financial progress will appear here."
      >
        <p className="text-sm text-text-secondary">No loan application on this lead yet.</p>
      </DashboardPanel>
    );
  }

  return (
    <DashboardPanel
      title={applications.length === 1 ? "Loan application" : "Loan applications"}
      description="Review the application, update its progress, and record complete transaction history."
    >
      <div className="space-y-6">
        {applications.map((application) => (
          <article key={application.id} className="overflow-hidden rounded-xl border border-border">
            <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-muted/25 px-4 py-3.5 sm:px-5">
              <div>
                <h3 className="font-semibold text-text-primary">{application.loan_type_name}</h3>
                <p className="mt-0.5 text-sm text-text-secondary">
                  {application.bank_name ?? "Bank not assigned"}
                  {application.amount_requested
                    ? ` · ${formatINR(Number(application.amount_requested))} requested`
                    : ""}
                </p>
              </div>
              <Badge variant="secondary">
                {STATUS_LABEL[application.status] ?? application.status}
              </Badge>
            </header>

            <div className="space-y-6 p-4 sm:p-5">
              {application.form_schema_snapshot && application.form_answers ? (
                <details className="group rounded-xl border border-border bg-muted/15">
                  <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
                    <span className="inline-flex items-center gap-2">
                      <span aria-hidden="true" className="text-text-secondary transition-transform group-open:rotate-90">›</span>
                      View submitted application details
                    </span>
                  </summary>
                  <div className="border-t border-border p-3">
                    <FormAnswerSummary
                      schema={application.form_schema_snapshot}
                      answers={application.form_answers}
                    />
                  </div>
                </details>
              ) : null}

              <section aria-labelledby={`progress-heading-${application.id}`} className="space-y-3">
                <div>
                  <h3 id={`progress-heading-${application.id}`} className="text-sm font-semibold text-text-primary">
                    Application progress
                  </h3>
                  <p className="mt-0.5 text-xs leading-5 text-text-secondary">
                    Move the application forward or record approved lending terms.
                  </p>
                </div>
                <LoanProgressForm
                  application={{
                    id: application.id,
                    loan_type_id: application.loan_type_id,
                    status: application.status,
                    status_reason: application.status_reason ?? null,
                    amount_sanctioned: application.amount_sanctioned ?? null,
                    bank_id: application.bank_id ?? null,
                    interest_rate: application.interest_rate ?? null,
                    processing_fee: application.processing_fee ?? null,
                    fee_outcome: application.fee_outcome ?? null,
                    closed_at: application.closed_at ?? null,
                  }}
                  onUpdate={onUpdateApp}
                />
              </section>

              <section aria-labelledby={`history-heading-${application.id}`} className="space-y-3 border-t border-border pt-5">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <h3 id={`history-heading-${application.id}`} className="text-sm font-semibold text-text-primary">
                      Transaction history
                    </h3>
                    <p className="mt-0.5 text-xs leading-5 text-text-secondary">
                      Immutable snapshots entered by the assigned Telecaller.
                    </p>
                  </div>
                  <AddTxnDialog
                    applicationId={application.id}
                    loanTypeName={application.loan_type_name}
                    defaultBankName={application.bank_name}
                    onAdd={onAddTxn}
                  />
                </div>
                <TransactionHistory application={application} />
              </section>
            </div>
          </article>
        ))}
      </div>
    </DashboardPanel>
  );
}
