import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CONTACT_METHOD_LABEL,
  addEmail,
  getActiveContactChange,
  newValueError,
  selfServiceStep,
  startContactChange,
  verifyNewValue,
} from "./contact-change";

function mockFetch(status: number, body: unknown) {
  return vi.fn(async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}

const CHALLENGE = {
  change_id: "6f1d2c3b-0000-4000-8000-000000000001",
  kind: "self_service",
  field: "mobile",
  status: "awaiting_current_otp",
  expires_at: "2026-11-17T10:15:00Z",
  message: "We sent a code to your current number.",
  destination_hint: "***3210",
  delivery_channel: "none",
  otp_hint: "123456",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("selfServiceStep()", () => {
  it("maps every server status to the screen the dialog shows", () => {
    expect(selfServiceStep("awaiting_current_otp")).toBe("current-code");
    expect(selfServiceStep("awaiting_new_value")).toBe("new-value");
    expect(selfServiceStep("awaiting_new_otp")).toBe("new-code");
    for (const status of ["completed", "cancelled", "expired", "rejected", "pending_approval"] as const) {
      expect(selfServiceStep(status)).toBe("done");
    }
  });
});

describe("newValueError()", () => {
  it("accepts an E.164 number and a plausible email", () => {
    expect(newValueError("mobile", "+919876543210")).toBeNull();
    expect(newValueError("email", "jane@example.com")).toBeNull();
  });

  it("rejects empty and malformed values", () => {
    expect(newValueError("mobile", "")).toMatch(/new number/);
    expect(newValueError("mobile", "98765")).toMatch(/valid/);
    expect(newValueError("email", " ")).toMatch(/new email/);
    expect(newValueError("email", "jane@")).toMatch(/valid/);
  });
});

describe("history labels", () => {
  it("names every method the API returns", () => {
    expect(Object.keys(CONTACT_METHOD_LABEL).sort()).toEqual(
      ["admin_approved", "email_added", "lost_number_recovery", "self_service"].sort(),
    );
  });
});

describe("API wrappers", () => {
  it("starts a change with the field and password and maps the challenge", async () => {
    const fetchMock = mockFetch(200, CHALLENGE);
    vi.stubGlobal("fetch", fetchMock);
    const res = await startContactChange("mobile", "Secret@123");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/auth/contact-change/start");
    expect(JSON.parse(init.body as string)).toEqual({
      field: "mobile",
      current_password: "Secret@123",
    });
    expect(res.ok && res.data).toMatchObject({
      changeId: CHALLENGE.change_id,
      destinationHint: "***3210",
      otpHint: "123456",
    });
  });

  it("adds an email with the password", async () => {
    const fetchMock = mockFetch(200, { ...CHALLENGE, kind: "email_add", field: "email" });
    vi.stubGlobal("fetch", fetchMock);
    await addEmail("jane@example.com", "Secret@123");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/auth/email/add");
    expect(JSON.parse(init.body as string)).toEqual({
      email: "jane@example.com",
      current_password: "Secret@123",
    });
  });

  it("reports that every session ended after the new value is verified", async () => {
    vi.stubGlobal("fetch", mockFetch(200, { message: "Changed.", signed_out: true }));
    const res = await verifyNewValue(CHALLENGE.change_id, "654321");
    expect(res.ok && res.data.signedOut).toBe(true);
  });

  it("maps an empty active change to null", async () => {
    vi.stubGlobal("fetch", mockFetch(200, { change: null }));
    const res = await getActiveContactChange();
    expect(res.ok && res.data).toBeNull();
  });

  it("passes a 409 through for an active change", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch(409, {
        detail: "Another phone or email change is already in progress. Finish or cancel it first.",
      }),
    );
    const res = await startContactChange("email", "Secret@123");
    expect(res.ok).toBe(false);
    if (!res.ok) expect(res.status).toBe(409);
  });
});
