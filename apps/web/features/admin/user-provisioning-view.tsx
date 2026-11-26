"use client";

import * as React from "react";
import type { components } from "@contracts/generated/schema";
import { ACCESS_LINES, ASSIGNMENTS, type SubAdminGrant } from "@/lib/sub-admin-access";
import { getSubAdminAccessHistory, setSubAdminAccess } from "@/lib/admin-api";
import { SubAdminGrantEditor } from "./sub-admin-grant-editor";
import { formatDate } from "@/lib/format";
import { Loader2, Maximize2, ShieldCheck, UserPlus } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { FieldError, RequiredIndicator } from "@/components/ui/field-error";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DASHBOARD_ICONS } from "@/features/dashboard/dashboard-icons";
import { FilterSelect } from "@/features/dashboard/filter-select";
import {
  DashboardHeader,
  DashboardPage,
  DashboardPanel,
  MetricCard,
  MetricGrid,
} from "@/features/dashboard/dashboard-ui";
import { DataTable, DataTablePrimaryCell, type DataColumn } from "@/features/dashboard/data-table";
import { EMPTY_FILTERS, FilterBar, matchesSearch } from "@/features/dashboard/filter-bar";
import {
  PANEL_DIALOG_WIDE_CLASS,
  WORKSPACE_DIALOG_CLASS,
  WorkspaceDialogHeader,
} from "@/features/dashboard/workspace-dialog";
import {
  createStaff,
  getStaffAccess,
  setStaffFeature,
  type StaffAccessEntry,
  type StaffAccessList,
  type StaffCreateRequest,
  type StaffCreateResponse,
} from "@/lib/admin-api";
import {
  apiIssuesToFieldErrors,
  emailError,
  focusFirstInvalidField,
  requiredTextError,
} from "@/lib/form-validation";
import { MobileInput } from "@/components/auth/mobile-input";
import { isValidMobile, toE164 } from "@/lib/phone";

import { TempCredentialPanel } from "./temp-credential-panel";
import { OperationalUsersPanel } from "./operational-users-panel";
import { LoanSpecialtySelect } from "./loan-specialty-select";

type StaffRole = StaffCreateRequest["role"];
type AccessStatus = "loading" | "ready" | "restricted" | "error";

const ROLE_OPTIONS: { value: StaffRole; label: string }[] = [
  { value: "admin", label: "Admin" },
  { value: "sub_admin", label: "Sub Admin" },
  { value: "telecaller", label: "Telecaller" },
  { value: "employee", label: "Officer" },
];

const LINE_OPTIONS: { value: "loans" | "real_estate" | "both"; label: string }[] = [
  { value: "loans", label: "Loans" },
  { value: "real_estate", label: "Real Estate" },
  { value: "both", label: "Both" },
];

const LINE_LABEL = Object.fromEntries(
  LINE_OPTIONS.map((option) => [option.value, option.label]),
) as Record<(typeof LINE_OPTIONS)[number]["value"], string>;

const EMPTY_FORM = {
  first_name: "",
  last_name: "",
  mobile: "",
  email: "",
  role: "sub_admin" as StaffRole,
  business_line: "" as "" | "loans" | "real_estate" | "both",
  loan_specialty_id: "",
};

export function UserProvisioningView() {
  const [form, setForm] = React.useState(EMPTY_FORM);
  const [submitting, setSubmitting] = React.useState(false);
  const [result, setResult] = React.useState<StaffCreateResponse | null>(null);
  const [access, setAccess] = React.useState<StaffAccessList | null>(null);
  const [accessStatus, setAccessStatus] = React.useState<AccessStatus>("loading");
  const [subAdminGrants, setSubAdminGrants] = React.useState<SubAdminGrant[]>([]);
  const [pendingAdmins, setPendingAdmins] = React.useState<StaffAccessEntry[]>([]);
  const [editingAccess, setEditingAccess] = React.useState<StaffAccessEntry | null>(null);
  const [featureBusy, setFeatureBusy] = React.useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});
  const [createOpen, setCreateOpen] = React.useState(false);
  const [staffAccessOpen, setStaffAccessOpen] = React.useState(false);
  const [operationalOpen, setOperationalOpen] = React.useState(false);
  const formRef = React.useRef<HTMLFormElement>(null);

  const needsLine = form.role !== "admin" && form.role !== "sub_admin";
  const canSpecialize = form.role === "telecaller" && (form.business_line === "loans" || form.business_line === "both");
  const visibleRoleOptions = access
    ? ROLE_OPTIONS
    : ROLE_OPTIONS.filter((option) => option.value !== "admin");

  const refreshAccess = React.useCallback(async () => {
    setAccessStatus("loading");
    const response = await getStaffAccess();
    if (response.ok) {
      setAccess(response.data);
      setAccessStatus("ready");
      return;
    }
    setAccess(null);
    if (response.status === 403) {
      const pending = await getStaffAccess(true);
      setPendingAdmins(pending.ok ? pending.data.entries : []);
    }
    setAccessStatus(response.status === 403 ? "restricted" : "error");
  }, []);

  React.useEffect(() => {
    void refreshAccess();
  }, [refreshAccess]);

  function setField<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((prev) => {
      const next = { ...prev, [key]: value };
      if (next.role !== "telecaller" || !["loans", "both"].includes(next.business_line)) next.loan_specialty_id = "";
      return next;
    });
    setFieldErrors((current) => {
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const next: Record<string, string> = {};
    const firstNameError = requiredTextError(form.first_name, "First name", 100);
    const lastNameError = requiredTextError(form.last_name, "Last name", 100);
    const mobileError = !form.mobile.trim()
      ? "Mobile number is required."
      : isValidMobile(form.mobile)
        ? undefined
        : "Enter a valid 10-digit Indian mobile number.";
    const nextEmailError = emailError(form.email, { required: true });
    if (firstNameError) next.first_name = firstNameError;
    if (lastNameError) next.last_name = lastNameError;
    if (mobileError) next.mobile = mobileError;
    if (nextEmailError) next.email = nextEmailError;
    if (needsLine && !form.business_line) next.business_line = "Choose a business line.";
    setFieldErrors(next);
    if (Object.keys(next).length > 0) {
      requestAnimationFrame(() => {
        if (formRef.current) focusFirstInvalidField(formRef.current);
      });
      return;
    }
    setSubmitting(true);
    const res = await createStaff({
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim(),
      mobile: toE164(form.mobile),
      email: form.email.trim(),
      role: form.role,
      sub_admin_grants: form.role === "sub_admin" && access ? subAdminGrants : undefined,
      loan_specialty_id: canSpecialize ? form.loan_specialty_id || null : null,
      business_line: needsLine
        ? (form.business_line as "loans" | "real_estate" | "both")
        : null,
    });
    setSubmitting(false);
    if (res.ok) {
      toast.success("Account created");
      setResult(res.data);
      setForm(EMPTY_FORM);
      setSubAdminGrants([]);
      void refreshAccess();
    } else {
      const serverErrors = apiIssuesToFieldErrors(res.issues, {
        first_name: "first_name",
        last_name: "last_name",
        mobile: "mobile",
        email: "email",
        role: "role",
        business_line: "business_line",
      });
      if (Object.keys(serverErrors).length > 0) setFieldErrors(serverErrors);
      toast.error("Could not create account", { description: res.error });
    }
  }

  const subAdmins = access?.entries.filter((entry) => entry.role === "sub_admin" && (!entry.sub_admin_access || entry.sub_admin_access.status === "active") && !entry.suspended) ?? [];
  const payoutDelegates = subAdmins.filter((entry) =>
    entry.features.includes("payout_requests"),
  ).length;
  const additionalAdminSlots = access
    ? Math.max(access.additional_admin_limit - access.additional_admin_count, 0)
    : null;

  return (
    <DashboardPage>
      <DashboardHeader
        title="Users & staff"
        description="Provision operational accounts, assign business-line scope, and manage delegated access."
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <UserPlus className="h-4 w-4" aria-hidden="true" />
            Create staff account
          </Button>
        }
      />

      <MetricGrid>
        <MetricCard
          label="Provisionable roles"
          value={visibleRoleOptions.length}
          hint={access ? "Includes additional Admins" : "Sub Admin, Telecaller, Officer"}
          icon={DASHBOARD_ICONS.usersAndStaff}
        />
        <MetricCard
          label="Line-scoped roles"
          value="2"
          hint="Telecaller and Officer"
          icon={DASHBOARD_ICONS.accessControl}
        />
        <MetricCard
          label="Additional Admin slots"
          value={additionalAdminSlots ?? "—"}
          hint={access ? `${access.additional_admin_count} of ${access.additional_admin_limit} active` : "Main Admin view only"}
          icon={DASHBOARD_ICONS.usersAndStaff}
        />
        <MetricCard
          label="Payout delegates"
          value={access ? payoutDelegates : "—"}
          hint={access ? `${subAdmins.length} active Sub Admins` : "Main Admin view only"}
          icon={DASHBOARD_ICONS.payouts}
        />
      </MetricGrid>

      <Dialog
        open={createOpen}
        onOpenChange={(open) => {
          if (!open && submitting) return;
          setCreateOpen(open);
          if (!open) {
            setResult(null);
            setFieldErrors({});
          }
        }}
      >
        <DialogContent preventOutsideClose showCloseButton={false} className={PANEL_DIALOG_WIDE_CLASS}>
          <WorkspaceDialogHeader
            title={result ? "Staff account created" : "Create staff account"}
            description={
              result
                ? "Share the one-use setup link below. The account remains available if link creation needs a retry."
                : "Assign the narrowest role and business-line scope needed for this account."
            }
            closeLabel="Close staff creation"
          />
          <div className="min-h-0 overflow-y-auto py-1">
            {result ? (
              <ProvisioningResult result={result} onReset={() => setResult(null)} />
            ) : (
              <form ref={formRef} className="space-y-5" onSubmit={(event) => void onSubmit(event)} noValidate>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <Label htmlFor="first_name">First name<RequiredIndicator /></Label>
                    <Input
                      id="first_name"
                      name="first_name"
                      autoComplete="given-name"
                      required
                      maxLength={100}
                      value={form.first_name}
                      onChange={(event) => setField("first_name", event.target.value)}
                      aria-invalid={Boolean(fieldErrors.first_name)}
                      aria-describedby={fieldErrors.first_name ? "first-name-error" : undefined}
                    />
                    <FieldError id="first-name-error" className="mt-1">{fieldErrors.first_name}</FieldError>
                  </div>
                  <div>
                    <Label htmlFor="last_name">Last name<RequiredIndicator /></Label>
                    <Input
                      id="last_name"
                      name="last_name"
                      autoComplete="family-name"
                      required
                      maxLength={100}
                      value={form.last_name}
                      onChange={(event) => setField("last_name", event.target.value)}
                      aria-invalid={Boolean(fieldErrors.last_name)}
                      aria-describedby={fieldErrors.last_name ? "last-name-error" : undefined}
                    />
                    <FieldError id="last-name-error" className="mt-1">{fieldErrors.last_name}</FieldError>
                  </div>
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <Label htmlFor="mobile">Mobile number<RequiredIndicator /></Label>
                    <MobileInput
                      id="mobile"
                      name="mobile"
                      autoComplete="tel"
                      size="sm"
                      required
                      placeholder="98765 43210"
                      value={form.mobile}
                      onChange={(event) => setField("mobile", event.target.value)}
                      aria-invalid={Boolean(fieldErrors.mobile)}
                      aria-describedby={fieldErrors.mobile ? "staff-mobile-error" : undefined}
                    />
                    <FieldError id="staff-mobile-error" className="mt-1">{fieldErrors.mobile}</FieldError>
                  </div>
                  <div>
                    <Label htmlFor="email">Email<RequiredIndicator /></Label>
                    <Input
                      id="email"
                      name="email"
                      autoComplete="email"
                      type="email"
                      required
                      maxLength={254}
                      value={form.email}
                      onChange={(event) => setField("email", event.target.value)}
                      aria-invalid={Boolean(fieldErrors.email)}
                      aria-describedby={fieldErrors.email ? "staff-email-error" : undefined}
                    />
                    <FieldError id="staff-email-error" className="mt-1">{fieldErrors.email}</FieldError>
                  </div>
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <Label htmlFor="role">Role</Label>
                    <Select
                      name="role"
                      value={form.role}
                      onValueChange={(value) =>
                        setForm((prev) => ({
                          ...prev,
                          role: value as StaffRole,
                          business_line: "",
                          loan_specialty_id: "",
                        }))
                      }
                    >
                      <SelectTrigger id="role">
                        <SelectValue placeholder="Choose a role" />
                      </SelectTrigger>
                      <SelectContent>
                        {visibleRoleOptions.map((option) => (
                          <SelectItem
                            key={option.value}
                            value={option.value}
                            disabled={
                              option.value === "admin" && additionalAdminSlots === 0
                            }
                          >
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  {needsLine ? (
                    <div>
                        <Label htmlFor="business_line">Business line<RequiredIndicator /></Label>
                      <Select
                        name="business_line"
                        value={form.business_line}
                        onValueChange={(value) =>
                          setField(
                            "business_line",
                            value as "loans" | "real_estate" | "both",
                          )
                        }
                      >
                          <SelectTrigger id="business_line" aria-required="true" aria-invalid={Boolean(fieldErrors.business_line)} aria-describedby={fieldErrors.business_line ? "business-line-error" : undefined}>
                          <SelectValue placeholder="Choose a line" />
                        </SelectTrigger>
                        <SelectContent>
                          {LINE_OPTIONS.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                              {option.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                        </Select>
                        <FieldError id="business-line-error" className="mt-1">{fieldErrors.business_line}</FieldError>
                    </div>
                  ) : (
                    <div className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs leading-5 text-text-secondary">
                      Additional Admins can create a pending Sub Admin account. Main Admin chooses its dashboard access.
                    </div>
                  )}
                </div>

                {canSpecialize && <LoanSpecialtySelect id="create-loan-specialty" value={form.loan_specialty_id} onChange={(value) => setField("loan_specialty_id", value)} disabled={submitting} />}

                {form.role === "sub_admin" && access ? (
                  <SubAdminGrantEditor grants={subAdminGrants} onChange={setSubAdminGrants} disabled={submitting} />
                ) : null}

                <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs leading-5 text-text-secondary">
                  A one-use setup link is generated after creation. If link creation needs a retry,
                  a temporary password is shown only as a fallback for a new identity.
                </div>

                <Button type="submit" disabled={submitting}>
                  {submitting ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <UserPlus className="h-4 w-4" aria-hidden="true" />
                  )}
                  {submitting ? "Creating account…" : "Create account"}
                </Button>
              </form>
            )}
          </div>
        </DialogContent>
      </Dialog>

      <DashboardPanel
        title="Staff access"
        description="Admin hierarchy and delegated operational capabilities"
        action={
          <Button variant="outline" size="sm" onClick={() => setStaffAccessOpen(true)}>
            <Maximize2 className="h-4 w-4" aria-hidden="true" />
            Full view
          </Button>
        }
      >
        <StaffAccessContent
          compact
          access={access}
          status={accessStatus}
          featureBusy={featureBusy}
          pendingEntries={pendingAdmins}
          onEditAccess={setEditingAccess}
          onRetry={refreshAccess}
          onFeatureChange={async (staffProfileUuid, enabled) => {
            setFeatureBusy(staffProfileUuid);
            const response = await setStaffFeature(staffProfileUuid, enabled);
            setFeatureBusy(null);
            if (response.ok) {
              setAccess(response.data);
              setAccessStatus("ready");
              toast.success(enabled ? "Payout access granted" : "Payout access revoked", {
                description: "The Sub Admin must sign in again.",
              });
            } else {
              toast.error("Could not update access", { description: response.error });
            }
          }}
        />
      </DashboardPanel>

      <Dialog open={staffAccessOpen} onOpenChange={setStaffAccessOpen}>
        <DialogContent showCloseButton={false} className={WORKSPACE_DIALOG_CLASS}>
          <WorkspaceDialogHeader
            title="Staff access"
            description="Review Admin hierarchy and manage delegated Sub Admin capabilities."
            closeLabel="Close staff access"
          />
          <DashboardPanel
            title="Access directory"
            description="Use the advanced filters to find the account whose delegation should change."
            className="min-h-0 overflow-y-auto"
          >
            <StaffAccessContent
              access={access}
              status={accessStatus}
              featureBusy={featureBusy}
          pendingEntries={pendingAdmins}
          onEditAccess={setEditingAccess}
              onRetry={refreshAccess}
              onFeatureChange={async (staffProfileUuid, enabled) => {
                setFeatureBusy(staffProfileUuid);
                const response = await setStaffFeature(staffProfileUuid, enabled);
                setFeatureBusy(null);
                if (response.ok) {
                  setAccess(response.data);
                  setAccessStatus("ready");
                  toast.success(enabled ? "Payout access granted" : "Payout access revoked", {
                    description: "The Sub Admin must sign in again.",
                  });
                } else {
                  toast.error("Could not update access", { description: response.error });
                }
              }}
            />
          </DashboardPanel>
        </DialogContent>
      </Dialog>

      {editingAccess ? (
        <SubAdminAccessDialog
          key={editingAccess.staff_profile_uuid}
          entry={editingAccess}
          onClose={() => setEditingAccess(null)}
          onSaved={(updated) => { setAccess(updated); setEditingAccess(null); }}
        />
      ) : null}

      <DashboardPanel
        title="Operational accounts"
        description="Platform-wide account oversight. Suspending an account immediately invalidates its sessions; deleted and Main Admin accounts are protected."
        action={
          <Button variant="outline" size="sm" onClick={() => setOperationalOpen(true)}>
            <Maximize2 className="h-4 w-4" aria-hidden="true" />
            Full view
          </Button>
        }
      >
        <OperationalUsersPanel compact />
      </DashboardPanel>

      <Dialog open={operationalOpen} onOpenChange={setOperationalOpen}>
        <DialogContent showCloseButton={false} className={WORKSPACE_DIALOG_CLASS}>
          <WorkspaceDialogHeader
            title="Operational accounts"
            description="Search every account and inspect role, profile, sign-in, and status details."
            closeLabel="Close operational accounts"
          />
          <div className="min-h-0 overflow-y-auto py-1">
            <OperationalUsersPanel />
          </div>
        </DialogContent>
      </Dialog>
    </DashboardPage>
  );
}

function ProvisioningResult({
  result,
  onReset,
}: {
  result: StaffCreateResponse;
  onReset: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-border bg-muted/30 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="font-medium text-text-primary">
              {result.first_name} {result.last_name}
            </p>
            <p className="mt-1 text-sm text-text-secondary">{result.mobile}</p>
          </div>
          <Badge variant="outline">{result.staff_code}</Badge>
        </div>
        <p className="mt-3 text-sm text-text-secondary">
          {ROLE_OPTIONS.find((role) => role.value === result.role)?.label ?? result.role}
          {result.business_line ? ` · ${LINE_LABEL[result.business_line]}` : " · Platform"}
        </p>
      </div>

      {result.temp_password ? null : (
        <p className="rounded-xl border border-border bg-muted/30 p-4 text-sm text-text-secondary">
          This mobile number already had an account. Its existing password still works, so no new
          credential was issued.
        </p>
      )}

      {/* The link half is reachable either way — an account that kept its old
          password still needs a route to the setup handoff. */}
      <TempCredentialPanel
        mobile={result.mobile}
        tempPassword={result.temp_password ?? undefined}
        authUserUuid={result.auth_user_uuid}
        autoCreate
      />

      <Button variant="outline" onClick={onReset}>
        <UserPlus className="h-4 w-4" aria-hidden="true" />
        Provision another
      </Button>
    </div>
  );
}

function StaffAccessContent({
  access,
  status,
  featureBusy,
  pendingEntries,
  onEditAccess,
  onRetry,
  onFeatureChange,
  compact = false,
}: {
  access: StaffAccessList | null;
  status: AccessStatus;
  featureBusy: string | null;
  pendingEntries: StaffAccessEntry[];
  onEditAccess: (entry: StaffAccessEntry) => void;
  onRetry: () => Promise<void>;
  onFeatureChange: (staffProfileUuid: string, enabled: boolean) => Promise<void>;
  compact?: boolean;
}) {
  const [filters, setFilters] = React.useState(EMPTY_FILTERS);
  const [mainFilter, setMainFilter] = React.useState("all");
  if (status === "loading") {
    return (
      <div className="flex min-h-48 items-center justify-center gap-2 text-sm text-text-secondary">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        Loading staff access…
      </div>
    );
  }

  if (status === "restricted") {
    return (
      <div className="flex min-h-48 items-start gap-3 rounded-xl border border-border bg-muted/30 p-4">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-brand-link">
          <ShieldCheck className="h-5 w-5" aria-hidden="true" />
        </span>
        <div>
          <p className="font-medium text-text-primary">Main Admin controls</p>
          <p className="mt-1 text-sm leading-6 text-text-secondary">
            You can provision Sub Admin, Telecaller, and Officer accounts. Only the Main Admin
            can activate Sub Admin accounts and manage their dashboard access.
          </p>
          {pendingEntries.length ? (
            <ul className="mt-3 space-y-1 text-sm">
              {pendingEntries.map((entry) => <li key={entry.staff_profile_uuid}>{entry.first_name} {entry.last_name} · {entry.staff_code} · Pending access</li>)}
            </ul>
          ) : null}
        </div>
      </div>
    );
  }

  if (status === "error" || !access) {
    return (
      <div className="flex min-h-48 flex-col items-start justify-center rounded-xl border border-border bg-muted/30 p-4">
        <p className="font-medium text-text-primary">Staff access is unavailable</p>
        <p className="mt-1 text-sm text-text-secondary">
          Provisioning remains available. Retry the hierarchy and delegation view.
        </p>
        <Button className="mt-4" variant="outline" size="sm" onClick={() => void onRetry()}>
          Retry
        </Button>
      </div>
    );
  }

  const filteredEntries = access.entries.filter((entry) => {
    if (
      filters.search &&
      !matchesSearch(
        `${entry.first_name} ${entry.last_name} ${entry.staff_code} ${entry.role}`,
        filters.search,
      )
    ) return false;
    if (filters.kind !== "all" && entry.role !== filters.kind) return false;
    const delegated = entry.features.includes("payout_requests");
    if (filters.status === "delegated" && !delegated) return false;
    if (filters.status === "not_delegated" && delegated) return false;
    if (mainFilter === "main" && !entry.is_primary_admin) return false;
    if (mainFilter === "additional" && entry.is_primary_admin) return false;
    return true;
  });

  if (compact) {
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-muted/30 px-4 py-3">
          <div>
            <p className="text-sm font-medium text-text-primary">Additional Admin capacity</p>
            <p className="mt-0.5 text-xs text-text-secondary">
              Main Admin does not consume an additional slot.
            </p>
          </div>
          <Badge variant="outline">
            {access.additional_admin_count} / {access.additional_admin_limit} active
          </Badge>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          {access.entries.slice(0, 4).map((entry) => (
            <div key={entry.staff_profile_uuid} className="rounded-xl border border-border p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="font-medium text-text-primary">
                    {entry.first_name} {entry.last_name}
                  </p>
                  <p className="mt-0.5 text-xs text-text-secondary">{entry.staff_code}</p>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <Badge variant="outline">
                    {entry.role === "sub_admin" ? "Sub Admin" : "Admin"}
                  </Badge>
                  {entry.is_primary_admin ? (
                    <Badge className="bg-brand-cta-tint text-brand-link">Main</Badge>
                  ) : null}
                </div>
              </div>
              <p className="mt-3 text-xs text-text-secondary">
                {entry.role === "sub_admin"
                  ? entry.sub_admin_access ? accessLabel(entry) : entry.features.includes("payout_requests")
                    ? "Can prepare payout requests"
                    : "No delegated payout access"
                  : entry.is_primary_admin
                    ? "Full platform control"
                    : "Admin operations"}
              </p>
              {entry.role === "sub_admin" ? <Button type="button" className="mt-2" size="sm" variant="outline" onClick={() => onEditAccess(entry)}>Edit access</Button> : null}
            </div>
          ))}
        </div>
        {access.entries.length > 4 ? (
          <p className="text-xs text-text-secondary">
            {access.entries.length - 4} more record(s) are available in Full view.
          </p>
        ) : null}
      </div>
    );
  }

  const columns: DataColumn<(typeof access.entries)[number]>[] = [
    {
      key: "staff",
      header: "Staff member",
      render: (entry) => (
        <DataTablePrimaryCell
          title={`${entry.first_name} ${entry.last_name}`}
          subtitle={entry.staff_code}
        />
      ),
    },
    {
      key: "role",
      header: "Role",
      render: (entry) => (
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="outline">{entry.role === "sub_admin" ? "Sub Admin" : "Admin"}</Badge>
          {entry.is_primary_admin ? (
            <Badge className="bg-brand-cta-tint text-brand-link">Main</Badge>
          ) : null}
        </div>
      ),
    },
    {
      key: "scope",
      header: "Scope",
      render: () => <span className="text-text-secondary">Platform</span>,
    },
    {
      key: "delegation",
      header: "Delegated access",
      render: (entry) => {
        if (entry.role === "sub_admin" && entry.sub_admin_access) {
          return <div className="flex items-center gap-2"><span>{accessLabel(entry)}</span><Button type="button" size="sm" variant="outline" onClick={() => onEditAccess(entry)}>Edit access</Button></div>;
        }
        const enabled = entry.features.includes("payout_requests");
        const busy = featureBusy === entry.staff_profile_uuid;
        return entry.role === "sub_admin" ? (
          <div className="flex flex-wrap items-center gap-2">
          <label className="inline-flex items-center gap-2 text-sm text-text-primary">
            <input
              type="checkbox"
              className="h-4 w-4 accent-brand-cta"
              checked={enabled}
              disabled={busy}
              onChange={(event) =>
                void onFeatureChange(entry.staff_profile_uuid, event.target.checked)
              }
            />
            Prepare payout requests
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : null}
          </label>
          <Button type="button" variant="outline" size="sm" onClick={() => onEditAccess(entry)}>Set scoped access</Button>
          </div>
        ) : (
          <span className="text-text-secondary">
            {entry.is_primary_admin ? "Full platform control" : "Admin operations"}
          </span>
        );
      },
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-muted/30 px-4 py-3">
        <div>
          <p className="text-sm font-medium text-text-primary">Additional Admin capacity</p>
          <p className="mt-0.5 text-xs text-text-secondary">
            Main Admin is permanent and does not consume an additional slot.
          </p>
        </div>
        <Badge variant="outline">
          {access.additional_admin_count} / {access.additional_admin_limit} active
        </Badge>
      </div>

      <FilterBar
        value={filters}
        onChange={setFilters}
        searchLabel="Search staff access"
        searchPlaceholder="Name or staff code"
        statusOptions={[
          { value: "delegated", label: "Payout access enabled" },
          { value: "not_delegated", label: "No payout delegation" },
        ]}
        statusLabel="Payout delegation"
        kindOptions={[
          { value: "admin", label: "Admin" },
          { value: "sub_admin", label: "Sub Admin" },
        ]}
        kindLabel="Role"
        showLine={false}
        showDates={false}
        onClear={() => {
          setFilters(EMPTY_FILTERS);
          setMainFilter("all");
        }}
        hasExternalFilters={mainFilter !== "all"}
        note={`${filteredEntries.length} of ${access.entries.length} access records shown.`}
        extra={
          <FilterSelect
            label="Admin hierarchy"
            value={mainFilter}
            options={[
              { value: "main", label: "Main Admin only" },
              { value: "additional", label: "Additional staff only" },
            ]}
            onValueChange={setMainFilter}
          />
        }
      />

      {filteredEntries.length > 0 ? (
        <div className="overflow-hidden rounded-xl border border-border">
          <DataTable
            columns={columns}
            rows={filteredEntries}
            rowKey={(entry) => entry.staff_profile_uuid}
          />
        </div>
      ) : (
        <p className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-text-secondary">
          No staff access records match these filters.
        </p>
      )}

      <p className="text-xs leading-5 text-text-secondary">
        Changing payout delegation invalidates the Sub Admin&apos;s current sessions; they must sign
        in again before the updated access takes effect.
      </p>
    </div>
  );
}

function accessLabel(entry: StaffAccessEntry) {
  if (entry.suspended) return "Suspended";
  switch (entry.sub_admin_access?.status) {
    case "pending": return "Pending access";
    case "inactive": return "Deactivated";
    case "active": return "Scoped access";
    default: return "Legacy access";
  }
}

function SubAdminAccessDialog({ entry, onClose, onSaved }: {
  entry: StaffAccessEntry;
  onClose: () => void;
  onSaved: (updated: StaffAccessList) => void;
}) {
  const [grants, setGrants] = React.useState<SubAdminGrant[]>(entry.sub_admin_access?.grants ?? []);
  const [busy, setBusy] = React.useState(false);
  const [deactivating, setDeactivating] = React.useState(false);
  const [error, setError] = React.useState("");
  const [history, setHistory] = React.useState<components["schemas"]["SubAdminAccessHistory"][] | null>(null);
  const [historyError, setHistoryError] = React.useState("");
  const teams = entry.live_teams ?? [];

  React.useEffect(() => {
    let active = true;
    void getSubAdminAccessHistory(entry.staff_profile_uuid).then((result) => {
      if (!active) return;
      if (result.ok) setHistory(result.data);
      else setHistoryError(result.error);
    });
    return () => { active = false; };
  }, [entry.staff_profile_uuid]);

  async function save(status: "active" | "inactive") {
    setBusy(true);
    setError("");
    const result = await setSubAdminAccess(entry.staff_profile_uuid, {
      status, grants: status === "active" ? grants : [],
      expected_version: entry.sub_admin_access?.version ?? 0,
    });
    setBusy(false);
    if (result.ok) {
      toast.success(status === "inactive" ? "Sub Admin deactivated" : "Dashboard access saved");
      onSaved(result.data);
    } else setError(result.error);
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose(); }}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{entry.first_name} {entry.last_name}</DialogTitle>
          <DialogDescription>{entry.staff_code} · {accessLabel(entry)}</DialogDescription>
        </DialogHeader>
        {entry.sub_admin_access ? null : <p className="text-sm text-text-secondary">Saving scoped access replaces this account’s legacy permissions and ends its current sessions.</p>}
        {teams.length ? (
          <div>
            <p className="text-sm font-medium">Assigned teams</p>
            <ul className="mt-1 text-sm text-text-secondary">{teams.map((team) => <li key={team.id}>{team.name} · {ACCESS_LINES[team.business_line]}</li>)}</ul>
            <p className="mt-1 text-xs text-text-secondary">Reassign these teams before deactivating the account.</p>
          </div>
        ) : null}
        <SubAdminGrantEditor grants={grants} onChange={setGrants} disabled={busy || deactivating} />
        <details className="rounded-lg border border-border p-3 text-sm">
          <summary className="cursor-pointer font-medium">Access history</summary>
          {historyError ? <p className="mt-2 text-destructive">{historyError}</p> : history === null ? <p className="mt-2">Loading history…</p> : history.length ? (
            <ol className="mt-2 space-y-2 text-text-secondary">
              {history.map((item) => <li key={item.after.version}>{formatDate(item.created_at)} · {item.before?.status ?? "New or legacy"} → {item.after.status}
                {item.after.grants.length ? <ul className="pl-3 text-xs">{item.after.grants.map((grant) => <li key={grant.assignment + grant.business_line}>{ASSIGNMENTS[grant.assignment].label} · {ACCESS_LINES[grant.business_line]}</li>)}</ul> : null}
              </li>)}
            </ol>
          ) : <p className="mt-2 text-text-secondary">No recorded dashboard access changes.</p>}
        </details>
        {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
        {deactivating ? <p className="text-sm">Deactivation ends active sessions and removes dashboard grants. Attendance and approvals stay in the record.</p> : null}
        <div className="flex flex-wrap justify-end gap-2">
          {deactivating ? (
            <><Button variant="outline" onClick={() => setDeactivating(false)} disabled={busy}>Cancel</Button>
              <Button variant="destructive" onClick={() => void save("inactive")} disabled={busy}>Confirm deactivation</Button></>
          ) : (
            <>{entry.sub_admin_access?.status !== "inactive" && teams.length === 0 ? <Button variant="outline" onClick={() => setDeactivating(true)} disabled={busy}>Deactivate</Button> : null}
              <Button onClick={() => void save("active")} disabled={busy || entry.suspended}>{entry.sub_admin_access && entry.sub_admin_access.status !== "active" ? "Activate with these grants" : "Save dashboard access"}</Button></>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
