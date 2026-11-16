import { describe, expect, it } from "vitest";

import { panoramaShapeError } from "@/lib/panorama-check";

describe("panoramaShapeError()", () => {
  it("accepts 2:1 panoramas from the lowered minimum upward", () => {
    expect(panoramaShapeError("a.jpg", 1024, 512)).toBeNull();
    expect(panoramaShapeError("b.jpg", 1774, 887)).toBeNull();
    expect(panoramaShapeError("c.jpg", 6000, 3000)).toBeNull();
  });

  it("explains why the images from the dev report were rejected", () => {
    expect(panoramaShapeError("tall.jpg", 4000, 6000)).toContain("twice as wide");
    expect(panoramaShapeError("small.jpg", 1000, 500)).toContain("at least 1024 × 512");
  });

  it("rejects panoramas above 25 megapixels", () => {
    expect(panoramaShapeError("huge.jpg", 8000, 4000)).toContain("25 megapixels");
  });
});
