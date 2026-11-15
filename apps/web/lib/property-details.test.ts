import { describe, expect, it } from "vitest";

import { rows, type Details } from "@/lib/property-details";

const PROJECT = {
  kind: "project_residence",
  project_name: "Sunny Homes",
  project_area_acres: 4.5,
  number_of_towers: 3,
  total_units: 120,
  configurations: ["2_5_bhk", "3_5_bhk"],
  unit_or_plot_area_sqft: 1150,
  unit_or_plot_area_max_sqft: 1450,
  uds_sqft: null,
  uds_area_from: 40,
  uds_area_to: 60,
  uds_area_unit: "sqyd",
  price_per_sqft_paise: 650_000,
  sale_type: "new_sale",
  expected_handover_date: null,
  plot_facing: "east",
  entrance_facing: "east",
  local_approval: { authority: "HMDA", reference_number: "LP/12/2024" },
  amenities_description: "Gardens",
  about_project: "Calm",
} as unknown as NonNullable<Details>;

function value(label: string, details = PROJECT) {
  return rows(details).find((row) => row.label === label)?.value;
}

describe("listing detail rows (CS-018)", () => {
  it("shows half-BHK configurations and From-To areas", () => {
    expect(value("Configurations")).toBe("2.5 BHK, 3.5 BHK");
    expect(value("Unit or flat area")).toBe("1,150 – 1,450 sq ft");
    expect(value("Undivided share")).toBe("40 – 60 sq yd");
  });

  it("labels flat facing and the local approval number", () => {
    expect(value("Flat facing")).toBe("East");
    expect(value("Local approval")).toBe("HMDA · No. LP/12/2024");
  });

  it("still shows a legacy single undivided share in sq ft", () => {
    const legacy = {
      ...PROJECT,
      uds_sqft: 420,
      uds_area_from: null,
      uds_area_to: null,
      uds_area_unit: null,
      unit_or_plot_area_max_sqft: null,
    } as unknown as NonNullable<Details>;
    expect(value("Undivided share", legacy)).toBe("420 sq ft");
    expect(value("Unit or flat area", legacy)).toBe("1,150 sq ft");
  });
});
