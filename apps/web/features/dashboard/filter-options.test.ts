import { describe, expect, it, vi } from "vitest";

import {
  compactChips,
  filterAriaLabel,
  optionLabel,
  optionsFromLabels,
  selectFilterChip,
  textFilterChip,
} from "./filter-options";
import { moreFiltersLabel } from "./more-filters";

describe("filter naming", () => {
  it("names every filter 'Filter by <field>'", () => {
    expect(filterAriaLabel("Status")).toBe("Filter by status");
    expect(filterAriaLabel("Lead source")).toBe("Filter by lead source");
    expect(filterAriaLabel("Business line")).toBe("Filter by business line");
  });

  it("keeps acronyms intact", () => {
    expect(filterAriaLabel("RERA review")).toBe("Filter by RERA review");
  });

  it("turns label maps into options in key order", () => {
    expect(optionsFromLabels({ hot: "Hot", warm: "Warm" })).toEqual([
      { value: "hot", label: "Hot" },
      { value: "warm", label: "Warm" },
    ]);
    expect(optionLabel([{ value: "hot", label: "Hot" }], "hot")).toBe("Hot");
    expect(optionLabel([], "unknown")).toBe("unknown");
  });

  it("counts hidden filters on the More filters control", () => {
    expect(moreFiltersLabel(0)).toBe("More filters");
    expect(moreFiltersLabel(3)).toBe("More filters (3)");
  });
});

describe("active filter chips", () => {
  it("has no chip while a select is unfiltered", () => {
    expect(selectFilterChip("interest", "Lead interest", "all", { hot: "Hot" }, () => {})).toBeNull();
    expect(selectFilterChip("interest", "Lead interest", undefined, { hot: "Hot" }, () => {})).toBeNull();
  });

  it("names the field and the chosen option, and removes through the callback", () => {
    const onRemove = vi.fn();
    const chip = selectFilterChip("source", "Lead source", "agent", { agent: "Referred by agent" }, onRemove);
    expect(chip?.label).toBe("Lead source: Referred by agent");
    chip?.onRemove();
    expect(onRemove).toHaveBeenCalledOnce();
  });

  it("chips trimmed text and drops blanks", () => {
    expect(textFilterChip("ref", "Referred by ID", "  AG-12 ", () => {})?.label).toBe("Referred by ID: AG-12");
    expect(textFilterChip("ref", "Referred by ID", "   ", () => {})).toBeNull();
    expect(compactChips([null, { id: "a", label: "A", onRemove: () => {} }, null])).toHaveLength(1);
  });
});
