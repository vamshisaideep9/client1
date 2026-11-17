"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { EmailVerifyBanner } from "@/components/auth/email-verify-banner";
import { useAuth } from "@/components/auth/session-provider";
import {
  OptionalProfileFields,
  optionalProfilePayload,
  validateOptionalProfile,
  type OptionalProfileDraft,
} from "@/components/profile/optional-profile-fields";
import { DeleteAccountDialog } from "@/components/settings/delete-account-dialog";
import { FieldError, RequiredIndicator } from "@/components/ui/field-error";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { FetchError } from "@/features/dashboard/fetch-error";
import { useMe } from "@/features/dashboard/me-provider";
import { PushSubscriptionCard } from "@/features/push-notifications/push-subscription-card";
import { JourneyDetailsCard } from "@/features/settings/journey-details-card";
import { PayoutDetailsCard } from "@/features/settings/payout-details-card";
import { PersonalizationSettingsCard } from "@/features/settings/personalization-settings-card";
import { settingsForRole } from "@/features/settings/settings-by-role";
import { AppearanceSettingsCard } from "@/features/settings/appearance-settings-card";
import { ContactDetailsCard } from "@/features/settings/contact-details-card";
import { updateProfile, type Me } from "@/lib/auth";
import {
  apiIssuesToFieldErrors,
  focusFirstInvalidField,
  requiredTextError,
} from "@/lib/form-validation";

export default function SettingsPage() {
  const { session } = useAuth();
  const { me, status, error, errorStatus, retry, setMe } = useMe();
  const [emailJustVerified, setEmailJustVerified] = React.useState(false);
  const emailVerified = me?.emailVerified ?? session?.emailVerified ?? false;
  const showEmailBanner = Boolean(me?.email) && !emailVerified && !emailJustVerified;
  const includePersonalDetails = session?.role === "client";
  // Unknown until the session loads, so nothing role-specific flashes first.
  const sections = session ? settingsForRole(session.role) : null;

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 sm:px-6 lg:px-10">
      <div>
        <h1 className="text-2xl font-semibold text-text-primary">
          {includePersonalDetails ? "Profile" : "Account settings"}
        </h1>
        <p className="text-sm text-text-secondary">
          {includePersonalDetails
            ? "Your account details and personal profile."
            : "Your account details and notification preferences."}
        </p>
      </div>

      {showEmailBanner && <EmailVerifyBanner onVerified={() => setEmailJustVerified(true)} />}

      {status === "loading" ? (
        <Skeleton className="h-72 rounded-xl" />
      ) : status === "error" ? (
        <FetchError status={errorStatus} message={error} onRetry={retry} />
      ) : me && sections && !sections.profileEditable ? (
        <ReadOnlyProfile firstName={me.firstName} lastName={me.lastName} />
      ) : me && sections ? (
        <ProfileForm
          key={`${me.firstName}|${me.lastName}|${me.gender}|${me.incomeAmountMinor}|${me.occupation}|${me.location}|${me.pincode}`}
          firstName={me.firstName}
          lastName={me.lastName}
          gender={me.gender}
          genderSelfDescription={me.genderSelfDescription}
          incomeSource={me.incomeSource}
          incomeAmountMinor={me.incomeAmountMinor}
          incomePeriod={me.incomePeriod}
          occupation={me.occupation}
          location={me.location}
          pincode={me.pincode}
          place={me.place}
          includePersonalDetails={includePersonalDetails}
          onSaved={setMe}
        />
      ) : null}

      {status === "ready" && me && sections ? (
        <ContactDetailsCard
          me={me}
          mode={sections.contactChange}
          onMeChange={(next) => {
            setMe(next);
            setEmailJustVerified(next.emailVerified);
          }}
        />
      ) : null}

      {session?.role === "client" ? <JourneyDetailsCard /> : null}

      {session?.role === "agent" ? <PayoutDetailsCard /> : null}

      <AppearanceSettingsCard />
      <PushSubscriptionCard />

      {sections?.personalization ? <PersonalizationSettingsCard /> : null}

      {sections?.deleteAccount ? (
        <div className="space-y-3 rounded-xl border border-destructive/30 bg-destructive/5 p-6">
          <div>
            <h2 className="text-sm font-semibold text-text-primary">Danger zone</h2>
            <p className="text-sm text-text-secondary">
              Permanently delete your account and personal details.
            </p>
          </div>
          <DeleteAccountDialog />
        </div>
      ) : null}
    </div>
  );
}

/**
 * Telecaller, Employee and Sub Admin accounts are managed by an Admin
 * (CS-021): their details are shown, not edited, and the API refuses changes.
 */
function ReadOnlyProfile({ firstName, lastName }: { firstName: string; lastName: string }) {
  const rows: { label: string; value: React.ReactNode }[] = [
    { label: "First name", value: firstName },
    { label: "Last name", value: lastName },
  ];
  return (
    <section aria-labelledby="profile-details-heading" className="space-y-4 rounded-xl border border-border bg-card p-6">
      <div>
        <h2 id="profile-details-heading" className="text-base font-semibold text-text-primary">
          Your details
        </h2>
        <p className="text-sm text-text-secondary">
          Your Admin manages these details. To change your name, ask an Admin; to change your
          phone number or email, send a request below.
        </p>
      </div>
      <dl className="grid gap-4 sm:grid-cols-2">
        {rows.map((row) => (
          <div key={row.label} className="min-w-0 space-y-1">
            <dt className="text-xs font-medium text-text-secondary">{row.label}</dt>
            <dd className="break-words text-sm text-text-primary">{row.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function ProfileForm({
  firstName: initialFirst,
  lastName: initialLast,
  gender: initialGender,
  genderSelfDescription: initialGenderSelfDescription,
  incomeSource: initialIncomeSource,
  incomeAmountMinor: initialIncomeAmountMinor,
  incomePeriod: initialIncomePeriod,
  occupation: initialOccupation,
  location: initialLocation,
  pincode: initialPincode,
  place,
  includePersonalDetails,
  onSaved,
}: {
  firstName: string;
  lastName: string;
  gender: Me["gender"];
  genderSelfDescription: Me["genderSelfDescription"];
  incomeSource: Me["incomeSource"];
  incomeAmountMinor: Me["incomeAmountMinor"];
  incomePeriod: Me["incomePeriod"];
  occupation: Me["occupation"];
  location: Me["location"];
  pincode: Me["pincode"];
  place: Me["place"];
  includePersonalDetails: boolean;
  onSaved: (next: Me) => void;
}) {
  const [firstName, setFirstName] = React.useState(initialFirst);
  const [lastName, setLastName] = React.useState(initialLast);
  const [optionalProfile, setOptionalProfile] = React.useState<OptionalProfileDraft>({
    gender: initialGender ?? "",
    genderSelfDescription: initialGenderSelfDescription ?? "",
    incomeSource: initialIncomeSource ?? "",
    incomeAmountRupees:
      initialIncomeAmountMinor === null ? "" : String(initialIncomeAmountMinor / 100),
    incomePeriod: initialIncomePeriod ?? "",
    occupation: initialOccupation ?? "",
    location: initialLocation ?? "",
    pincode: initialPincode ?? "",
  });
  const [saving, setSaving] = React.useState(false);
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});
  const formRef = React.useRef<HTMLFormElement>(null);

  const optionalChanged = includePersonalDetails && (
    optionalProfile.gender !== (initialGender ?? "") ||
    optionalProfile.genderSelfDescription.trim() !== (initialGenderSelfDescription ?? "") ||
    optionalProfile.incomeSource !== (initialIncomeSource ?? "") ||
    optionalProfile.incomeAmountRupees !==
      (initialIncomeAmountMinor === null ? "" : String(initialIncomeAmountMinor / 100)) ||
    optionalProfile.incomePeriod !== (initialIncomePeriod ?? "") ||
    optionalProfile.occupation.trim() !== (initialOccupation ?? "") ||
    optionalProfile.location.trim() !== (initialLocation ?? "") ||
    optionalProfile.pincode.trim() !== (initialPincode ?? ""));
  const dirty =
    firstName.trim() !== initialFirst || lastName.trim() !== initialLast || optionalChanged;
  const canSave = dirty && !saving;

  function validate() {
    const next: Record<string, string> = {};
    const firstNameError = requiredTextError(firstName, "First name", 100);
    const lastNameError = requiredTextError(lastName, "Last name", 100);
    if (firstNameError) next.firstName = firstNameError;
    if (lastNameError) next.lastName = lastNameError;
    if (includePersonalDetails) Object.assign(next, validateOptionalProfile(optionalProfile));
    setFieldErrors(next);
    if (Object.keys(next).length > 0) {
      requestAnimationFrame(() => {
        if (formRef.current) focusFirstInvalidField(formRef.current);
      });
    }
    return Object.keys(next).length === 0;
  }

  function clearError(field: string) {
    setFieldErrors((current) => {
      if (!current[field]) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSave || !validate()) return;
    setSaving(true);
    const basePayload = {
      firstName: firstName.trim(),
      lastName: lastName.trim(),
    };
    let res;
    if (includePersonalDetails) {
      const parsed = optionalProfilePayload(optionalProfile);
      if (!parsed.ok) {
        setSaving(false);
        setFieldErrors((current) => ({ ...current, [parsed.field]: parsed.error }));
        toast.error(parsed.error);
        return;
      }
      res = await updateProfile({ ...basePayload, ...parsed.data });
    } else {
      res = await updateProfile(basePayload);
    }
    setSaving(false);
    if (res.ok) {
      onSaved(res.data);
      toast.success("Profile updated.", { description: "Your details have been saved." });
    } else {
      const serverErrors = apiIssuesToFieldErrors(res.issues, {
        first_name: "firstName",
        last_name: "lastName",
        gender_self_description: "genderSelfDescription",
        income_amount_minor: "incomeAmountRupees",
        income_period: "incomePeriod",
        occupation: "occupation",
        location: "location",
        pincode: "pincode",
      });
      if (Object.keys(serverErrors).length > 0) setFieldErrors(serverErrors);
      toast.error(res.error || "Couldn't save your changes.", {
        description: "Please check your details and try again.",
      });
    }
  }

  return (
    <form ref={formRef} onSubmit={handleSubmit} noValidate className="space-y-6 rounded-xl border border-border bg-card p-6">
      <div className="grid gap-5 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="first-name">First name<RequiredIndicator /></Label>
          <Input
            id="first-name"
            value={firstName}
            onChange={(e) => { setFirstName(e.target.value); clearError("firstName"); }}
            maxLength={100}
            autoComplete="given-name"
            aria-invalid={Boolean(fieldErrors.firstName)}
            aria-describedby={fieldErrors.firstName ? "first-name-error" : undefined}
          />
          <FieldError id="first-name-error">{fieldErrors.firstName}</FieldError>
        </div>
        <div className="space-y-2">
          <Label htmlFor="last-name">Last name<RequiredIndicator /></Label>
          <Input
            id="last-name"
            value={lastName}
            onChange={(e) => { setLastName(e.target.value); clearError("lastName"); }}
            maxLength={100}
            autoComplete="family-name"
            aria-invalid={Boolean(fieldErrors.lastName)}
            aria-describedby={fieldErrors.lastName ? "last-name-error" : undefined}
          />
          <FieldError id="last-name-error">{fieldErrors.lastName}</FieldError>
        </div>
        <p className="text-xs text-text-secondary sm:col-span-2">
          Your phone number and email are changed in “Phone and email” below.
        </p>

        {includePersonalDetails ? (
          <div className="border-t border-border pt-5 sm:col-span-2">
            <div className="mb-4">
              <h2 className="text-sm font-semibold text-text-primary">Additional details</h2>
              <p className="text-xs text-text-secondary">
                These details are optional and can be removed at any time.
              </p>
            </div>
            <OptionalProfileFields
              idPrefix="settings-profile"
              value={optionalProfile}
              onChange={(next) => { setOptionalProfile(next); setFieldErrors((current) => {
                const remaining = { ...current };
                for (const key of Object.keys(next)) delete remaining[key];
                return remaining;
              }); }}
              disabled={saving}
              errors={fieldErrors}
              initialPlace={place}
            />
          </div>
        ) : null}
      </div>

      <div className="flex justify-end">
        <button
          type="submit"
          disabled={!canSave}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-loans-accent px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-loans-accent/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {saving && <Loader2 className="h-4 w-4 animate-spin" />}
          {saving ? "Saving..." : "Save changes"}
        </button>
      </div>
    </form>
  );
}
