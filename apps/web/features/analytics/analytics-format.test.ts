import { describe, expect, it } from "vitest";

import {
  foldShareParts,
  formatDay,
  formatMetric,
  seriesColor,
  shareLabel,
} from "./analytics-format";

describe("analytics formatting", () => {
  it("formats each unit and shows a dash for missing values", () => {
    expect(formatMetric(null, "percent")).toBe("—");
    expect(formatMetric(42.25, "percent")).toBe("42.3%");
    expect(formatMetric(1234, "count")).toBe("1,234");
    expect(formatMetric(5.5, "hours")).toBe("5.5 h");
    expect(formatMetric(72, "hours")).toBe("3 days");
    expect(formatMetric(2500, "rupees")).toContain("2,500");
  });

  it("keeps series colors in fixed order and never cycles", () => {
    expect(seriesColor(0)).toBe("#2a78d6");
    expect(seriesColor(1)).toBe("#eb6834");
    expect(seriesColor(9)).toBe(seriesColor(3));
  });

  it("formats calendar days without a timezone shift", () => {
    expect(formatDay("2026-11-01")).toBe("1 Nov");
  });

  it("folds the smallest parts into Other but keeps category order", () => {
    const parts = [
      { key: "unassigned", label: "Unassigned", value: 1 },
      { key: "assigned", label: "Assigned", value: 5 },
      { key: "in_progress", label: "In progress", value: 3 },
      { key: "completed", label: "Completed", value: 9 },
      { key: "blocked", label: "Blocked", value: 2 },
    ];
    expect(foldShareParts(parts).map((part) => [part.key, part.value])).toEqual([
      ["assigned", 5],
      ["in_progress", 3],
      ["completed", 9],
      ["other", 3],
    ]);
    expect(foldShareParts(parts.slice(0, 3)).map((part) => part.key)).toEqual([
      "unassigned",
      "assigned",
      "in_progress",
    ]);
  });

  it("labels shares of a whole", () => {
    expect(shareLabel(1, 4)).toBe("25%");
    expect(shareLabel(0, 0)).toBe("0%");
  });
});
