"use client";

import * as React from "react";
import { Loader2, MapPinOff, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getPersonalizationPreference,
  grantPersonalizationLocationConsent,
  revokePersonalizationLocation,
  setPersonalizationPreference,
  type PersonalizationPreference,
} from "@/lib/personalization-api";

export function PersonalizationSettingsCard() {
  const [preference, setPreference] = React.useState<PersonalizationPreference | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    let active = true;
    void getPersonalizationPreference().then((result) => {
      if (!active) return;
      if (result.ok) setPreference(result.data);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

  async function setEnabled(enabled: boolean) {
    setBusy(true);
    const result = await setPersonalizationPreference(enabled);
    setBusy(false);
    if (result.ok) {
      setPreference(result.data);
      toast.success(enabled ? "Personalized content enabled." : "Personalized content disabled.");
    } else {
      toast.error(result.error);
    }
  }

  async function setAreaOffers(enabled: boolean) {
    setBusy(true);
    const result = enabled
      ? await grantPersonalizationLocationConsent()
      : await revokePersonalizationLocation();
    setBusy(false);
    if (result.ok) {
      setPreference(result.data);
      toast.success(enabled ? "Offers for your area turned on." : "Offers for your area turned off.");
    } else {
      toast.error(result.error);
    }
  }

  async function disableLocation() {
    setBusy(true);
    const result = await revokePersonalizationLocation();
    setBusy(false);
    if (result.ok) {
      setPreference(result.data);
      toast.success("Saved location removed.");
    } else {
      toast.error(result.error);
    }
  }

  if (loading) return <Skeleton className="h-56 rounded-xl" />;
  if (!preference) return null;

  return (
    <section className="space-y-5 rounded-xl border border-border bg-card p-6">
      <div className="flex items-start gap-3">
        <Sparkles className="mt-0.5 h-5 w-5 text-info" aria-hidden="true" />
        <div>
          <h2 className="text-sm font-semibold text-text-primary">Personalized dashboard</h2>
          <p className="mt-1 text-sm text-text-secondary">
            Use your account type and current application activity to choose useful dashboard
            highlights. This does not use browsing or click history.
          </p>
        </div>
      </div>

      <Label className="flex cursor-pointer items-start gap-3 rounded-lg border border-border p-4 font-normal">
        <Checkbox
          checked={preference.personalization_enabled}
          disabled={busy}
          onCheckedChange={(checked) => void setEnabled(checked === true)}
          aria-label="Enable personalized dashboard content"
        />
        <span>
          <span className="block text-sm font-medium text-text-primary">Personalized content</span>
          <span className="mt-1 block text-xs text-text-secondary">
            Turning this off also removes any saved personalization signals and turns off offers
            for your area.
          </span>
        </span>
      </Label>

      {/* CS-026: area offers need their own, separately revocable consent. */}
      <Label
        className={`flex items-start gap-3 rounded-lg border border-border p-4 font-normal ${
          preference.personalization_enabled ? "cursor-pointer" : "cursor-not-allowed opacity-60"
        }`}
      >
        <Checkbox
          checked={preference.location_enabled}
          disabled={busy || !preference.personalization_enabled}
          onCheckedChange={(checked) => void setAreaOffers(checked === true)}
          aria-label="Offers for your area, using your profile pincode"
        />
        <span>
          <span className="block text-sm font-medium text-text-primary">Offers for your area</span>
          <span className="mt-1 block text-xs text-text-secondary">
            Uses the pincode saved in your profile to show offers near you. Your device location
            is not used. Needs personalized content; turn it off at any time.
          </span>
        </span>
      </Label>

      {preference.location_enabled && preference.location_captured_at ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-muted/30 p-4">
          <div className="flex items-start gap-3">
            <MapPinOff className="mt-0.5 h-4 w-4 text-text-secondary" aria-hidden="true" />
            <div>
              <p className="text-sm font-medium text-text-primary">Saved personalization location</p>
              <p className="mt-1 text-xs text-text-secondary">
                Browser location capture is no longer available. Remove this previously saved point
                now, or it will expire automatically.
              </p>
              {preference.location_captured_at ? (
                <p className="mt-1 text-xs text-text-secondary">
                  Saved {new Date(preference.location_captured_at).toLocaleDateString()}.
                </p>
              ) : null}
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => void disableLocation()}
          >
            {busy ? (
              <Loader2
                className="h-4 w-4 animate-spin motion-reduce:animate-none"
                aria-hidden="true"
              />
            ) : (
              <MapPinOff className="h-4 w-4" aria-hidden="true" />
            )}
            {busy ? "Removing…" : "Remove saved location"}
          </Button>
        </div>
      ) : null}
    </section>
  );
}
