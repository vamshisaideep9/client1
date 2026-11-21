import { expect, test } from "@playwright/test";
import { buildSecurityHeaders } from "../lib/security-headers";

test("production media policy permits configured storage and blocks other origins", async ({ page }) => {
  const allowed = "https://storage.example.test/loan-preview.mp4";
  const denied = "https://untrusted.example.test/loan-preview.mp4";
  let allowedRequests = 0;
  let deniedRequests = 0;
  const headers = Object.fromEntries(buildSecurityHeaders({
    production: true,
    assetHost: "https://storage.example.test",
  }).map(({ key, value }) => [key, value]));

  // Exercise browser enforcement of the production policy without external
  // storage credentials or a real borrower's document. Decoding is not tested.
  await page.route("**/security-policy-probe", (route) => route.fulfill({
    contentType: "text/html",
    headers,
    body: "<!doctype html><html><body>Media policy probe</body></html>",
  }));
  await page.route(allowed, (route) => {
    allowedRequests++;
    return route.fulfill({ contentType: "video/mp4", body: "" });
  });
  await page.route(denied, (route) => {
    deniedRequests++;
    return route.fulfill({ contentType: "video/mp4", body: "" });
  });
  await page.goto("/security-policy-probe");
  const directive = await page.evaluate(async ({ allowed, denied }) => {
    const blocked = new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Expected a CSP violation")), 10_000);
      document.addEventListener("securitypolicyviolation", (event) => {
        if (event.blockedURI === denied) {
          clearTimeout(timer);
          resolve(event.effectiveDirective);
        }
      });
    });
    for (const src of [allowed, denied]) {
      const video = document.createElement("video");
      video.preload = "auto";
      video.src = src;
      document.body.append(video);
      video.load();
    }
    return blocked;
  }, { allowed, denied });
  await expect.poll(() => allowedRequests).toBeGreaterThan(0);
  expect(deniedRequests).toBe(0);
  expect(directive).toBe("media-src");
});
