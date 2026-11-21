import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";

import { middleware } from "./middleware";

describe("dashboard middleware", () => {
  it("preserves the exact property path for login", () => {
    const request = new NextRequest(
      "https://dhanadhara.example/dashboard/properties/123e4567-e89b-42d3-a456-426614174000?from=public",
    );
    const response = middleware(request);
    const location = new URL(response.headers.get("location")!);
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("return_to")).toBe(
      "/dashboard/properties/123e4567-e89b-42d3-a456-426614174000?from=public",
    );
  });

  it("lets a session hint continue to the dashboard guard", () => {
    const request = new NextRequest("https://dhanadhara.example/dashboard", {
      headers: { cookie: "session_hint=1" },
    });
    const response = middleware(request);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("sends an account that owes the email step to /add-email (CS-025)", () => {
    const request = new NextRequest("https://dhanadhara.example/dashboard/loans?tab=1", {
      headers: { cookie: "session_hint=1; email_required=1" },
    });
    const response = middleware(request);
    expect(new URL(response.headers.get("location")!).pathname).toBe("/add-email");
  });

  it("lets the add-email step load for a signed-in account", () => {
    const request = new NextRequest("https://dhanadhara.example/add-email", {
      headers: { cookie: "session_hint=1; email_required=1" },
    });
    expect(middleware(request).headers.get("x-middleware-next")).toBe("1");
  });

  it("sends a signed-out visitor of /add-email to login", () => {
    const response = middleware(new NextRequest("https://dhanadhara.example/add-email"));
    const location = new URL(response.headers.get("location")!);
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("return_to")).toBe("/dashboard");
  });

  it("ignores a cleared email hint", () => {
    const request = new NextRequest("https://dhanadhara.example/dashboard", {
      headers: { cookie: "session_hint=1; email_required=" },
    });
    expect(middleware(request).headers.get("x-middleware-next")).toBe("1");
  });
});
