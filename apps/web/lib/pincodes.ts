import type { components } from "@contracts/generated/schema";

import { apiRequest, type ApiResponse } from "@/lib/api/client";

type Schemas = components["schemas"];
export type PincodePlace = Schemas["PincodePlaceRead"];
export type PincodeDistrict = Schemas["PincodeDistrictRead"];

// CS-026: Indian pincodes are six digits and never start with 0.
export const PINCODE_PATTERN = /^[1-9]\d{5}$/;

export function isValidPincode(value: string): boolean {
  return PINCODE_PATTERN.test(value.trim());
}

/** "Area, District, State" without repeating a district equal to the area. */
export function formatPlace(place: Pick<PincodePlace, "area" | "district" | "state">): string {
  const parts = [place.area];
  if (place.district.toLowerCase() !== place.area.toLowerCase()) parts.push(place.district);
  parts.push(place.state);
  return parts.join(", ");
}

export function cityLabel(city: Pick<PincodeDistrict, "district" | "state">): string {
  return `${city.district}, ${city.state}`;
}

export function lookupPincode(pincode: string): Promise<ApiResponse<PincodePlace>> {
  return apiRequest<PincodePlace>(`/api/v1/pincodes/${encodeURIComponent(pincode.trim())}`);
}

/**
 * One-time position → nearest pincode. The position goes in the POST body
 * (never the URL) and the server does not keep it.
 */
export function nearestPincode(
  latitude: number,
  longitude: number,
): Promise<ApiResponse<PincodePlace>> {
  return apiRequest<PincodePlace>("/api/v1/pincodes/nearest", {
    method: "POST",
    body: { latitude, longitude } satisfies Schemas["NearestPincodeRequest"],
  });
}

export function listDistricts(): Promise<ApiResponse<PincodeDistrict[]>> {
  return apiRequest<PincodeDistrict[]>("/api/v1/pincodes/districts");
}

export type DevicePositionResult =
  | { ok: true; latitude: number; longitude: number }
  | { ok: false; error: string };

/**
 * Ask the browser for the current position once. Low accuracy is enough to
 * pick a pincode, and no cached or watched position is used.
 */
export function readDevicePositionOnce(
  geolocation: Geolocation | undefined = typeof navigator !== "undefined"
    ? navigator.geolocation
    : undefined,
): Promise<DevicePositionResult> {
  if (!geolocation) {
    return Promise.resolve({
      ok: false,
      error: "Your browser can't share your location. Enter your pincode instead.",
    });
  }
  return new Promise((resolve) => {
    geolocation.getCurrentPosition(
      (position) =>
        resolve({
          ok: true,
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        }),
      (error) =>
        resolve({
          ok: false,
          error:
            error.code === error.PERMISSION_DENIED
              ? "Location permission was not given. Enter your pincode instead."
              : "We couldn't get your location. Enter your pincode instead.",
        }),
      { enableHighAccuracy: false, maximumAge: 0, timeout: 15_000 },
    );
  });
}
