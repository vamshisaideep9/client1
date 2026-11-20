import { describe, expect, it } from "vitest";

import { CAMPAIGN_VIDEO_MAX_SECONDS, exceedsBannerVideoLength } from "@/lib/campaign-media-api";

describe("exceedsBannerVideoLength", () => {
  it("allows banner videos of up to one minute", () => {
    expect(CAMPAIGN_VIDEO_MAX_SECONDS).toBe(60);
    expect(exceedsBannerVideoLength(30)).toBe(false);
    expect(exceedsBannerVideoLength(60)).toBe(false);
  });

  it("flags a video longer than one minute", () => {
    expect(exceedsBannerVideoLength(60.5)).toBe(true);
  });

  it.each([null, Number.NaN, Number.POSITIVE_INFINITY])("leaves an unreadable duration (%s) to the server", (seconds) => {
    expect(exceedsBannerVideoLength(seconds)).toBe(false);
  });
});
