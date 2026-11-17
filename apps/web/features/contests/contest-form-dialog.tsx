"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { Textarea } from "@/components/ui/textarea";
import { DashboardFormSection } from "@/features/dashboard/dashboard-ui";
import { useProductCatalogue } from "@/features/dashboard/use-product-catalogue";
import {
  buildContestDefinition,
  emptyContestForm,
  formFromContest,
  metricOptions,
  scoredRole,
  usesBusiness,
  validateContestForm,
  type ContestFormState,
} from "@/lib/contest-form";
import {
  AUDIENCE_LABEL,
  CATEGORY_LABEL,
  DEAL_STAGE_LABEL,
  LINE_LABEL,
  LOAN_STAGE_LABEL,
  METRIC_LABEL,
  SUBTYPE_CATEGORY,
  SUBTYPE_LABEL,
  TEAM_ROLE_LABEL,
} from "@/lib/contest-rules";
import { createContest, updateContest, type Contest } from "@/lib/contests-api";
import { apiIssuesToFieldErrors, focusFirstInvalidField } from "@/lib/form-validation";

function todayIst(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
}

type Option = { value: string; label: string };

function ChoiceChips({
  legend,
  options,
  values,
  onChange,
  idPrefix,
}: {
  legend: string;
  options: readonly Option[];
  values: string[];
  onChange: (values: string[]) => void;
  idPrefix: string;
}) {
  if (options.length === 0) return null;
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium text-text-primary">{legend}</legend>
      <p className="text-xs text-text-secondary">Leave all unticked to count any.</p>
      <div className="flex flex-wrap gap-2">
        {options.map((option) => {
          const id = `${idPrefix}-${option.value}`;
          const checked = values.includes(option.value);
          return (
            <label
              key={option.value}
              htmlFor={id}
              className="inline-flex min-h-10 cursor-pointer items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm has-[[data-state=checked]]:border-brand-blue has-[[data-state=checked]]:bg-loans-soft"
            >
              <Checkbox
                id={id}
                checked={checked}
                onCheckedChange={(next) =>
                  onChange(
                    next === true
                      ? [...values, option.value]
                      : values.filter((value) => value !== option.value),
                  )
                }
              />
              {option.label}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function Field({
  id,
  label,
  error,
  hint,
  required = false,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>
        {label}
        {required ? <RequiredIndicator /> : null}
      </Label>
      {children}
      {hint ? <p className="text-xs text-text-secondary">{hint}</p> : null}
      <FieldError id={`${id}-error`}>{error}</FieldError>
    </div>
  );
}

function NumberInput({
  id,
  value,
  onChange,
  error,
  placeholder,
  money = false,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
  placeholder?: string;
  money?: boolean;
}) {
  return (
    <div className="relative">
      {money ? (
        <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-sm text-text-secondary">
          ₹
        </span>
      ) : null}
      <Input
        id={id}
        inputMode={money ? "decimal" : "numeric"}
        value={value}
        placeholder={placeholder}
        className={money ? "pl-7" : undefined}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

function Choice<T extends string>({
  id,
  value,
  options,
  onChange,
}: {
  id: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <Select value={value} onValueChange={(next) => onChange(next as T)}>
      <SelectTrigger id={id} className="w-full">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

const AUDIENCE_OPTIONS = (Object.keys(AUDIENCE_LABEL) as (keyof typeof AUDIENCE_LABEL)[]).map(
  (value) => ({ value, label: AUDIENCE_LABEL[value] }),
);

export function ContestFormDialog({
  open,
  contest,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  /** Editing an existing draft or rejected contest; null creates one. */
  contest: Contest | null;
  onOpenChange: (open: boolean) => void;
  onSaved: (contest: Contest) => void;
}) {
  const [form, setForm] = React.useState<ContestFormState>(() =>
    contest ? formFromContest(contest) : emptyContestForm(todayIst()),
  );
  const [citiesText, setCitiesText] = React.useState("");
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [busy, setBusy] = React.useState(false);
  const contentRef = React.useRef<HTMLDivElement>(null);
  const catalogue = useProductCatalogue(open && form.businessLine === "loans");

  React.useEffect(() => {
    if (open) {
      const initial = contest ? formFromContest(contest) : emptyContestForm(todayIst());
      setForm(initial);
      setCitiesText(initial.cities.join(", "));
      setErrors({});
    }
  }, [open, contest]);

  function set<Key extends keyof ContestFormState>(key: Key, value: ContestFormState[Key]) {
    setForm((current) => {
      const next = { ...current, [key]: value };
      // Keep the ranking metric one the audience can be measured on.
      if (!metricOptions(next).includes(next.metric)) next.metric = metricOptions(next)[0];
      return next;
    });
    setErrors((current) => {
      if (!current[key as string]) return current;
      const copy = { ...current };
      delete copy[key as string];
      return copy;
    });
  }

  function showErrors(next: Record<string, string>) {
    setErrors(next);
    if (Object.keys(next).length > 0) {
      requestAnimationFrame(() => {
        if (contentRef.current) focusFirstInvalidField(contentRef.current);
      });
    }
  }

  async function save() {
    const next = validateContestForm(form);
    showErrors(next);
    if (Object.keys(next).length > 0) return;
    setBusy(true);
    const body = buildContestDefinition(form);
    const response = contest ? await updateContest(contest.id, body) : await createContest(body);
    setBusy(false);
    if (response.ok) {
      toast.success(contest ? "Contest saved" : "Draft created", {
        description: "Submit it for approval when it is ready.",
      });
      onSaved(response.data);
      onOpenChange(false);
      return;
    }
    const serverErrors = apiIssuesToFieldErrors(response.issues, {
      title: "title",
      starts_on: "startsOn",
      ends_on: "endsOn",
      prize_paise: "prizeRupees",
      budget_cap_paise: "budgetCapRupees",
    });
    if (Object.keys(serverErrors).length > 0) showErrors(serverErrors);
    toast.error("Could not save the contest", { description: response.error });
  }

  const role = scoredRole(form);
  const business = usesBusiness(form);
  const isTeam = form.audience === "team";
  const loans = form.businessLine === "loans";
  const amountMetric = form.metric === "amount";
  const subtypeOptions = Object.entries(SUBTYPE_LABEL)
    .filter(([value]) => form.categories.length === 0 || form.categories.includes(SUBTYPE_CATEGORY[value]))
    .map(([value, label]) => ({ value, label }));

  return (
    <Dialog open={open} onOpenChange={(next) => (!busy ? onOpenChange(next) : undefined)}>
      <DialogContent
        ref={contentRef}
        className="max-h-[92dvh] w-[calc(100vw-2rem)] max-w-3xl overflow-y-auto sm:max-w-3xl"
      >
        <DialogHeader>
          <DialogTitle>{contest ? "Edit contest" : "New contest"}</DialogTitle>
          <DialogDescription>
            Saved as a draft. A platform Admin approves it before anyone sees it.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <DashboardFormSection title="Basics">
            <Field id="contest-title" label="Title" error={errors.title} required>
              <Input
                id="contest-title"
                value={form.title}
                maxLength={120}
                aria-invalid={errors.title ? true : undefined}
                aria-describedby={errors.title ? "contest-title-error" : undefined}
                onChange={(event) => set("title", event.target.value)}
              />
            </Field>
            <Field id="contest-description" label="Description" hint="What participants should aim for.">
              <Textarea
                id="contest-description"
                value={form.description}
                maxLength={2000}
                rows={2}
                onChange={(event) => set("description", event.target.value)}
              />
            </Field>
            <Field id="contest-terms" label="Terms" hint="Shown under the rules, for example how prizes are paid.">
              <Textarea
                id="contest-terms"
                value={form.terms}
                maxLength={4000}
                rows={2}
                onChange={(event) => set("terms", event.target.value)}
              />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field id="contest-line" label="Business line" required>
                <Choice
                  id="contest-line"
                  value={form.businessLine}
                  options={[
                    { value: "loans", label: LINE_LABEL.loans },
                    { value: "real_estate", label: LINE_LABEL.real_estate },
                  ]}
                  onChange={(value) => set("businessLine", value)}
                />
              </Field>
              <Field id="contest-audience" label="Who takes part" required>
                <Choice
                  id="contest-audience"
                  value={form.audience}
                  options={AUDIENCE_OPTIONS}
                  onChange={(value) => set("audience", value)}
                />
              </Field>
              {isTeam ? (
                <Field
                  id="contest-team-role"
                  label="Teams of"
                  hint="Teams compete on their combined result; their manager is the Sub Admin who runs them."
                >
                  <Choice
                    id="contest-team-role"
                    value={form.teamMemberRole}
                    options={[
                      { value: "telecaller", label: TEAM_ROLE_LABEL.telecaller },
                      { value: "employee", label: TEAM_ROLE_LABEL.employee },
                    ]}
                    onChange={(value) => set("teamMemberRole", value)}
                  />
                </Field>
              ) : null}
              <Field id="contest-starts" label="Starts on" error={errors.startsOn} required>
                <Input
                  id="contest-starts"
                  type="date"
                  value={form.startsOn}
                  min={todayIst()}
                  onChange={(event) => set("startsOn", event.target.value)}
                />
              </Field>
              <Field
                id="contest-ends"
                label="Ends on"
                error={errors.endsOn}
                hint="Both dates are included (India time)."
                required
              >
                <Input
                  id="contest-ends"
                  type="date"
                  value={form.endsOn}
                  min={form.startsOn}
                  aria-invalid={errors.endsOn ? true : undefined}
                  onChange={(event) => set("endsOn", event.target.value)}
                />
              </Field>
            </div>
          </DashboardFormSection>

          {business || role !== "agent" ? (
            <DashboardFormSection
              title={loans ? "Loan cases that count" : "Property deals that count"}
              description={
                role === "agent"
                  ? "Cases on leads the Agent introduced."
                  : role === "telecaller"
                    ? "Cases on leads the Telecaller holds. Optional for staff."
                    : "Cases on leads where the Employee completed a task before the counted stage. Optional for staff."
              }
            >
              {loans ? (
                <>
                  <ChoiceChips
                    legend="Loan products"
                    idPrefix="contest-product"
                    options={catalogue.loanTypes}
                    values={form.loanTypeIds}
                    onChange={(values) => set("loanTypeIds", values)}
                  />
                  <ChoiceChips
                    legend="Banks"
                    idPrefix="contest-bank"
                    options={catalogue.banks}
                    values={form.bankIds}
                    onChange={(values) => set("bankIds", values)}
                  />
                  <Field id="contest-loan-stage" label="Counted when">
                    <Choice
                      id="contest-loan-stage"
                      value={form.loanStage}
                      options={(Object.keys(LOAN_STAGE_LABEL) as (keyof typeof LOAN_STAGE_LABEL)[]).map(
                        (value) => ({ value, label: LOAN_STAGE_LABEL[value] }),
                      )}
                      onChange={(value) => set("loanStage", value)}
                    />
                  </Field>
                </>
              ) : (
                <>
                  <ChoiceChips
                    legend="Property categories"
                    idPrefix="contest-category"
                    options={Object.entries(CATEGORY_LABEL).map(([value, label]) => ({ value, label }))}
                    values={form.categories}
                    onChange={(values) =>
                      setForm((current) => ({
                        ...current,
                        categories: values,
                        subtypes: current.subtypes.filter(
                          (subtype) => values.length === 0 || values.includes(SUBTYPE_CATEGORY[subtype]),
                        ),
                      }))
                    }
                  />
                  <ChoiceChips
                    legend="Property types"
                    idPrefix="contest-subtype"
                    options={subtypeOptions}
                    values={form.subtypes}
                    onChange={(values) => set("subtypes", values)}
                  />
                  <ChoiceChips
                    legend="Sale or rent"
                    idPrefix="contest-intent"
                    options={[
                      { value: "sale", label: "Sale" },
                      { value: "rent", label: "Rent / lease" },
                    ]}
                    values={form.intents}
                    onChange={(values) => set("intents", values)}
                  />
                  <Field id="contest-cities" label="Cities" hint="Separate cities with commas. Leave empty for any city.">
                    <Input
                      id="contest-cities"
                      value={citiesText}
                      maxLength={2000}
                      onChange={(event) => {
                        setCitiesText(event.target.value);
                        set(
                          "cities",
                          event.target.value
                            .split(",")
                            .map((city) => city.trim())
                            .filter(Boolean),
                        );
                      }}
                    />
                  </Field>
                  <Field id="contest-deal-stage" label="Counted when">
                    <Choice
                      id="contest-deal-stage"
                      value={form.dealStage}
                      options={(Object.keys(DEAL_STAGE_LABEL) as (keyof typeof DEAL_STAGE_LABEL)[]).map(
                        (value) => ({ value, label: DEAL_STAGE_LABEL[value] }),
                      )}
                      onChange={(value) => set("dealStage", value)}
                    />
                  </Field>
                </>
              )}
              <div className="grid gap-4 sm:grid-cols-2">
                <Field
                  id="contest-case-min"
                  label={loans ? "Each case at least" : "Each deal at least"}
                  error={errors.perCaseMinRupees}
                >
                  <NumberInput
                    id="contest-case-min"
                    money
                    value={form.perCaseMinRupees}
                    error={errors.perCaseMinRupees}
                    onChange={(value) => set("perCaseMinRupees", value)}
                  />
                </Field>
                <Field
                  id="contest-case-max"
                  label={loans ? "Each case at most" : "Each deal at most"}
                  error={errors.perCaseMaxRupees}
                >
                  <NumberInput
                    id="contest-case-max"
                    money
                    value={form.perCaseMaxRupees}
                    error={errors.perCaseMaxRupees}
                    onChange={(value) => set("perCaseMaxRupees", value)}
                  />
                </Field>
                <Field id="contest-count-min" label={loans ? "Cases, at least" : "Deals, at least"} error={errors.countAtLeast}>
                  <NumberInput
                    id="contest-count-min"
                    value={form.countAtLeast}
                    error={errors.countAtLeast}
                    onChange={(value) => set("countAtLeast", value)}
                  />
                </Field>
                <Field
                  id="contest-count-max"
                  label={loans ? "Cases, at most (optional)" : "Deals, at most (optional)"}
                  error={errors.countAtMost}
                  hint="Only with an at-least count."
                >
                  <NumberInput
                    id="contest-count-max"
                    value={form.countAtMost}
                    error={errors.countAtMost}
                    onChange={(value) => set("countAtMost", value)}
                  />
                </Field>
                <Field
                  id="contest-total"
                  label={loans ? "Total amount, at least" : "Total value, at least"}
                  error={errors.totalAtLeastRupees}
                  hint={
                    loans
                      ? "Requested amount when submitted, sanctioned amount once approved."
                      : "Quoted price, or the listing price before a quote."
                  }
                >
                  <NumberInput
                    id="contest-total"
                    money
                    value={form.totalAtLeastRupees}
                    error={errors.totalAtLeastRupees}
                    onChange={(value) => set("totalAtLeastRupees", value)}
                  />
                </Field>
              </div>
            </DashboardFormSection>
          ) : null}

          {role !== "agent" ? (
            <DashboardFormSection title="Activity targets" description="Counted inside the contest dates.">
              <div className="grid gap-4 sm:grid-cols-2">
                {role === "telecaller" ? (
                  <>
                    <Field id="contest-calls" label="Calls logged, at least" error={errors.callsAtLeast}>
                      <NumberInput id="contest-calls" value={form.callsAtLeast} error={errors.callsAtLeast} onChange={(value) => set("callsAtLeast", value)} />
                    </Field>
                    <Field id="contest-followups" label="Follow-ups on time, at least" error={errors.followUpsAtLeast} hint="A call on the lead by the end of the day it was due.">
                      <NumberInput id="contest-followups" value={form.followUpsAtLeast} error={errors.followUpsAtLeast} onChange={(value) => set("followUpsAtLeast", value)} />
                    </Field>
                    <Field id="contest-rate" label="Connect rate, at least (%)" error={errors.connectRatePercent}>
                      <NumberInput id="contest-rate" value={form.connectRatePercent} error={errors.connectRatePercent} onChange={(value) => set("connectRatePercent", value)} />
                    </Field>
                    <Field id="contest-rate-calls" label="Over at least this many calls" error={errors.connectRateMinCalls}>
                      <NumberInput id="contest-rate-calls" value={form.connectRateMinCalls} error={errors.connectRateMinCalls} onChange={(value) => set("connectRateMinCalls", value)} />
                    </Field>
                  </>
                ) : (
                  <>
                    <Field id="contest-tasks" label="Tasks completed, at least" error={errors.tasksCompletedAtLeast}>
                      <NumberInput id="contest-tasks" value={form.tasksCompletedAtLeast} error={errors.tasksCompletedAtLeast} onChange={(value) => set("tasksCompletedAtLeast", value)} />
                    </Field>
                    <Field id="contest-ontime" label="Tasks on time, at least" error={errors.tasksOnTimeAtLeast}>
                      <NumberInput id="contest-ontime" value={form.tasksOnTimeAtLeast} error={errors.tasksOnTimeAtLeast} onChange={(value) => set("tasksOnTimeAtLeast", value)} />
                    </Field>
                  </>
                )}
                {form.businessLine === "real_estate" ? (
                  <Field id="contest-visits" label="Site visits completed, at least" error={errors.siteVisitsAtLeast}>
                    <NumberInput id="contest-visits" value={form.siteVisitsAtLeast} error={errors.siteVisitsAtLeast} onChange={(value) => set("siteVisitsAtLeast", value)} />
                  </Field>
                ) : null}
              </div>
            </DashboardFormSection>
          ) : null}

          <DashboardFormSection title="Who can take part" description="Everyone needs an active profile on this line.">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field id="contest-tenure" label="Joined at least (days before the start)">
                <NumberInput id="contest-tenure" value={form.minTenureDays} placeholder="0" onChange={(value) => set("minTenureDays", value)} />
              </Field>
              {role === "agent" ? (
                <label htmlFor="contest-kyc" className="flex min-h-10 items-center gap-2 self-end text-sm">
                  <Checkbox id="contest-kyc" checked={form.kycVerified} onCheckedChange={(next) => set("kycVerified", next === true)} />
                  KYC verified only
                </label>
              ) : null}
            </div>
          </DashboardFormSection>

          <DashboardFormSection title="Winning and prizes">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field id="contest-metric" label="Rank by">
                <Choice
                  id="contest-metric"
                  value={form.metric}
                  options={metricOptions(form).map((value) => ({ value, label: METRIC_LABEL[value] }))}
                  onChange={(value) => set("metric", value)}
                />
              </Field>
              <Field id="contest-win" label="Winners">
                <Choice
                  id="contest-win"
                  value={form.winMode}
                  options={[
                    { value: "threshold", label: "Everyone who hits every target" },
                    { value: "top_n", label: "The top N" },
                  ]}
                  onChange={(value) => set("winMode", value)}
                />
              </Field>
              {form.winMode === "top_n" ? (
                <Field id="contest-top-n" label="How many winners" error={errors.topN} hint="A tie at the last place is kept whole.">
                  <NumberInput id="contest-top-n" value={form.topN} error={errors.topN} onChange={(value) => set("topN", value)} />
                </Field>
              ) : null}
              {isTeam ? (
                <>
                  <Field id="contest-manager-prize" label="Manager prize" error={errors.managerPrizeRupees} required>
                    <NumberInput id="contest-manager-prize" money value={form.managerPrizeRupees} error={errors.managerPrizeRupees} onChange={(value) => set("managerPrizeRupees", value)} />
                  </Field>
                  <Field id="contest-member-prize" label="Prize per member" error={errors.memberPrizeRupees} required>
                    <NumberInput id="contest-member-prize" money value={form.memberPrizeRupees} error={errors.memberPrizeRupees} onChange={(value) => set("memberPrizeRupees", value)} />
                  </Field>
                  <Field
                    id="contest-member-min"
                    label={`Member minimum (${METRIC_LABEL[form.metric].toLowerCase()})`}
                    error={errors.memberMinimum}
                    hint="Members below it get no member prize."
                  >
                    <NumberInput id="contest-member-min" money={amountMetric} value={form.memberMinimum} error={errors.memberMinimum} onChange={(value) => set("memberMinimum", value)} />
                  </Field>
                </>
              ) : (
                <Field id="contest-prize" label="Prize per winner" error={errors.prizeRupees} required>
                  <NumberInput id="contest-prize" money value={form.prizeRupees} error={errors.prizeRupees} onChange={(value) => set("prizeRupees", value)} />
                </Field>
              )}
              <Field
                id="contest-cap"
                label="Budget cap (optional)"
                error={errors.budgetCapRupees}
                hint="Prizes are paid in rank order up to this total."
              >
                <NumberInput id="contest-cap" money value={form.budgetCapRupees} error={errors.budgetCapRupees} onChange={(value) => set("budgetCapRupees", value)} />
              </Field>
            </div>
          </DashboardFormSection>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={save} disabled={busy}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
            {contest ? "Save changes" : "Save draft"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
