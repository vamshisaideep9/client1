import { afterEach, describe, expect, it, vi } from "vitest";

import {
  cityLabel,
  formatPlace,
  isValidPincode,
  nearestPincode,
  readDevicePositionOnce,
} from "@/lib/pincodes";

describe("pincode helpers (CS-026)", () => {
  it("accepts six digits that don't start with 0", () => {
    expect(isValidPincode("500001")).toBe(true);
    expect(isValidPincode(" 110001 ")).toBe(true);
    for (const value of ["", "012345", "50001", "5000011", "50a001"]) {
      expect(isValidPincode(value)).toBe(false);
    }
  });

  it("formats a place without repeating a district equal to the area", () => {
    expect(formatPlace({ area: "Gachibowli", district: "Hyderabad", state: "Telangana" })).toBe(
      "Gachibowli, Hyderabad, Telangana",
    );
    expect(formatPlace({ area: "Hyderabad", district: "Hyderabad", state: "Telangana" })).toBe(
      "Hyderabad, Telangana",
    );
    expect(cityLabel({ district: "Hyderabad", state: "Telangana" })).toBe("Hyderabad, Telangana");
  });
});

describe("readDevicePositionOnce", () => {
  it("asks once, without high accuracy or a cached position", async () => {
    const getCurrentPosition = vi.fn(
      (success: PositionCallback, _error?: PositionErrorCallback, _options?: PositionOptions) =>
        success({ coords: { latitude: 17.44, longitude: 78.35 } } as GeolocationPosition),
    );
    const result = await readDevicePositionOnce({
      getCurrentPosition,
    } as unknown as Geolocation);
    expect(result).toEqual({ ok: true, latitude: 17.44, longitude: 78.35 });
    expect(getCurrentPosition).toHaveBeenCalledTimes(1);
    expect(getCurrentPosition.mock.calls[0][2]).toMatchObject({
      enableHighAccuracy: false,
      maximumAge: 0,
    });
  });

  it("explains a refused permission and a missing API", async () => {
    const denied = await readDevicePositionOnce({
      getCurrentPosition: (_: PositionCallback, error: PositionErrorCallback) =>
        error({ code: 1, PERMISSION_DENIED: 1 } as GeolocationPositionError),
    } as unknown as Geolocation);
    expect(denied).toEqual({ ok: false, error: expect.stringContaining("permission") });
    const missing = await readDevicePositionOnce(undefined);
    expect(missing.ok).toBe(false);
  });
});

describe("nearestPincode", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends the position in a POST body, never the URL", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ pincode: "500032", area: "Gachibowli", district: "Hyderabad", state: "Telangana" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const result = await nearestPincode(17.44123, 78.34871);
    expect(result.ok && result.data.pincode).toBe("500032");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/pincodes\/nearest$/);
    expect(url).not.toContain("17.44");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ latitude: 17.44123, longitude: 78.34871 });
  });
});
