import { describe, expect, it } from "vitest";

import {
  YOUTUBE_CTA_LABEL,
  isSafeBannerHref,
  isSafeExternalHref,
  resolveBannerCta,
  youtubeIdFromLink,
} from "./banner-cta";

const VIDEO_ID = "dQw4w9WgXcQ";

describe("isSafeExternalHref", () => {
  it.each([
    "https://partner.example/offer",
    "https://youtu.be/dQw4w9WgXcQ",
    "HTTPS://Example.com/path?x=1#y",
    "https://example.com:8443/",
  ])("accepts %s", (value) => {
    expect(isSafeExternalHref(value)).toBe(true);
  });

  it.each([
    "",
    "http://example.com",
    "javascript:alert(1)",
    "data:text/html,hi",
    "//evil.example",
    "https:/example.com",
    "https://u:p@example.com",
    "https://user@example.com",
    "https://@example.com",
    "https://example.com\\@good.example",
    "https://example.com:99999/",
    "https://exa mple.com",
    " https://example.com",
    "https://example.com/\n",
    "https://example.com/\u007f",
    "/loans",
  ])("rejects %j", (value) => {
    expect(isSafeExternalHref(value)).toBe(false);
  });
});

describe("isSafeBannerHref", () => {
  it("accepts a site path or an https link and nothing else", () => {
    expect(isSafeBannerHref("/loans")).toBe(true);
    expect(isSafeBannerHref("https://partner.example")).toBe(true);
    expect(isSafeBannerHref("loans")).toBe(false);
    expect(isSafeBannerHref("//evil.example")).toBe(false);
    expect(isSafeBannerHref("/\\evil.example")).toBe(false);
    expect(isSafeBannerHref("http://partner.example")).toBe(false);
  });
});

describe("resolveBannerCta", () => {
  it("keeps an internal path as a same-tab link", () => {
    expect(resolveBannerCta({ deepLink: "/loans", ctaLabel: "Explore" })).toEqual({
      href: "/loans",
      label: "Explore",
      external: false,
    });
  });

  it("marks an https link external", () => {
    expect(
      resolveBannerCta({ deepLink: "https://partner.example/offer", ctaLabel: "Visit partner" }),
    ).toEqual({ href: "https://partner.example/offer", label: "Visit partner", external: true });
  });

  it("drops an unsafe destination instead of trusting it", () => {
    for (const deepLink of ["javascript:alert(1)", "//evil.example", "http://partner.example"]) {
      expect(resolveBannerCta({ deepLink, ctaLabel: "Go" })).toBeNull();
    }
  });

  it("needs a label for an authored destination", () => {
    expect(resolveBannerCta({ deepLink: "/loans", ctaLabel: "  " })).toBeNull();
  });

  it("defaults to the YouTube video with a default label when there is no destination", () => {
    expect(resolveBannerCta({ deepLink: null, ctaLabel: null, youtubeVideoId: VIDEO_ID })).toEqual({
      href: `https://www.youtube.com/watch?v=${VIDEO_ID}`,
      label: YOUTUBE_CTA_LABEL,
      external: true,
    });
    expect(
      resolveBannerCta({ deepLink: "", ctaLabel: "See the tour", youtubeVideoId: VIDEO_ID }),
    ).toMatchObject({ label: "See the tour", external: true });
  });

  it("prefers the authored destination over the video", () => {
    expect(
      resolveBannerCta({ deepLink: "/loans", ctaLabel: "Explore", youtubeVideoId: VIDEO_ID }),
    ).toMatchObject({ href: "/loans", external: false });
  });

  it("ignores a malformed video id", () => {
    expect(resolveBannerCta({ youtubeVideoId: "not-an-id" })).toBeNull();
    expect(resolveBannerCta({ youtubeVideoId: "dQw4w9WgXcQ&x" })).toBeNull();
  });
});

describe("youtubeIdFromLink", () => {
  it.each([
    [VIDEO_ID, VIDEO_ID],
    [`https://www.youtube.com/watch?v=${VIDEO_ID}`, VIDEO_ID],
    [`https://youtu.be/${VIDEO_ID}?t=3`, VIDEO_ID],
    [`youtube.com/shorts/${VIDEO_ID}`, VIDEO_ID],
    [`https://www.youtube-nocookie.com/embed/${VIDEO_ID}`, VIDEO_ID],
  ])("reads %s", (value, expected) => {
    expect(youtubeIdFromLink(value)).toBe(expected);
  });

  it.each(["", "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ", "https://vimeo.com/1", "https://www.youtube.com/channel/x"])(
    "rejects %j",
    (value) => {
      expect(youtubeIdFromLink(value)).toBeNull();
    },
  );
});
