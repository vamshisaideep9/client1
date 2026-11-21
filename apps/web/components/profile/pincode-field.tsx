"use client";

import * as React from "react";
import { Loader2, LocateFixed, MapPin } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FieldError } from "@/components/ui/field-error";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  formatPlace,
  isValidPincode,
  lookupPincode,
  nearestPincode,
  readDevicePositionOnce,
  type PincodePlace,
} from "@/lib/pincodes";

type LookupState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "found"; place: PincodePlace }
  | { kind: "unknown" }
  | { kind: "error"; message: string };

// CS-026: optional profile pincode. A complete pincode is looked up to show
// its place name (area, district, state) from the built-in list; the name is
// never typed or saved as free text. "Use my location" asks the browser for
// the position once, the server maps it to the nearest pincode and keeps
// nothing; the person still decides whether to save it.
export function PincodeField({
  id,
  value,
  onChange,
  disabled = false,
  error,
  initialPlace = null,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  error?: string;
  initialPlace?: PincodePlace | null;
}) {
  const trimmed = value.trim();
  const [lookup, setLookup] = React.useState<LookupState>(() =>
    initialPlace && initialPlace.pincode === trimmed
      ? { kind: "found", place: initialPlace }
      : { kind: "idle" },
  );
  const [locating, setLocating] = React.useState(false);
  const [locateError, setLocateError] = React.useState<string | null>(null);
  const resolved = React.useRef<Map<string, PincodePlace | null>>(new Map());

  React.useEffect(() => {
    if (initialPlace) resolved.current.set(initialPlace.pincode, initialPlace);
  }, [initialPlace]);

  React.useEffect(() => {
    if (!isValidPincode(trimmed)) {
      setLookup({ kind: "idle" });
      return;
    }
    const known = resolved.current.get(trimmed);
    if (known !== undefined) {
      setLookup(known ? { kind: "found", place: known } : { kind: "unknown" });
      return;
    }
    let active = true;
    setLookup({ kind: "loading" });
    const timer = window.setTimeout(() => {
      void lookupPincode(trimmed).then((result) => {
        if (!active) return;
        if (result.ok) {
          resolved.current.set(trimmed, result.data);
          setLookup({ kind: "found", place: result.data });
        } else if (result.status === 404) {
          resolved.current.set(trimmed, null);
          setLookup({ kind: "unknown" });
        } else {
          setLookup({ kind: "error", message: "Couldn't look up this pincode right now." });
        }
      });
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [trimmed]);

  async function suggestFromDevice() {
    setLocateError(null);
    setLocating(true);
    const position = await readDevicePositionOnce();
    if (!position.ok) {
      setLocating(false);
      setLocateError(position.error);
      return;
    }
    const result = await nearestPincode(position.latitude, position.longitude);
    setLocating(false);
    if (!result.ok) {
      setLocateError(
        result.status === 404 || result.status === 422
          ? "We couldn't match your location to a pincode. Enter your pincode instead."
          : result.error,
      );
      return;
    }
    resolved.current.set(result.data.pincode, result.data);
    onChange(result.data.pincode);
  }

  const helpId = `${id}-help`;
  const placeId = `${id}-place`;
  const errorId = `${id}-error`;
  const describedBy = [placeId, helpId, error ? errorId : undefined].filter(Boolean).join(" ");

  return (
    <div className="space-y-2">
      <Label htmlFor={id}>Pincode</Label>
      <div className="flex flex-col gap-2 sm:flex-row">
        <Input
          id={id}
          name="pincode"
          value={value}
          onChange={(event) => {
            setLocateError(null);
            onChange(event.target.value.replace(/\D/g, "").slice(0, 6));
          }}
          inputMode="numeric"
          autoComplete="postal-code"
          maxLength={6}
          pattern="[1-9][0-9]{5}"
          placeholder="e.g. 500001"
          disabled={disabled}
          className="sm:max-w-40"
          aria-invalid={Boolean(error)}
          aria-describedby={describedBy}
        />
        <Button
          type="button"
          variant="outline"
          onClick={() => void suggestFromDevice()}
          disabled={disabled || locating}
        >
          {locating ? (
            <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
          ) : (
            <LocateFixed className="h-4 w-4" aria-hidden="true" />
          )}
          {locating ? "Finding your pincode…" : "Use my location"}
        </Button>
      </div>
      <p id={placeId} className="flex min-h-5 items-center gap-1.5 text-sm" aria-live="polite">
        {lookup.kind === "found" ? (
          <>
            <MapPin className="h-4 w-4 shrink-0 text-brand-link" aria-hidden="true" />
            <span className="text-text-primary">{formatPlace(lookup.place)}</span>
          </>
        ) : lookup.kind === "loading" ? (
          <span className="text-text-secondary">Looking up this pincode…</span>
        ) : lookup.kind === "unknown" ? (
          <span className="text-text-secondary">
            We don&apos;t have a place name for this pincode. You can still save it.
          </span>
        ) : lookup.kind === "error" ? (
          <span className="text-text-secondary">{lookup.message}</span>
        ) : null}
      </p>
      {locateError ? (
        <p className="text-sm text-text-secondary" role="status">
          {locateError}
        </p>
      ) : null}
      <p id={helpId} className="text-xs text-text-secondary">
        Optional. Your place name comes from the pincode. &ldquo;Use my location&rdquo; asks your
        browser for your position once to find the nearest pincode; we don&apos;t store your
        position, only the pincode you save. Place names:{" "}
        <a
          href="https://www.geonames.org/"
          target="_blank"
          rel="noopener noreferrer"
          className="underline underline-offset-2"
        >
          GeoNames
        </a>{" "}
        (CC BY 4.0).
      </p>
      <FieldError id={errorId}>{error}</FieldError>
    </div>
  );
}
