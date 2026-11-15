import { describe, expect, it } from "vitest";

import {
  buildSubmissionPayload,
  submissionIssuesToFieldErrors,
  submissionToFormState,
  validateForm,
  EMPTY_DETAILS,
  EMPTY_FORM,
  FURNISHING_OPTIONS,
  CONSTRUCTION_OPTIONS,
  type SubmitFormState,
} from "@/lib/property-submit";

const PROJECT_AMENITIES = Array.from({ length: 150 }, () => "landscaped").join(" ");

const VALID: SubmitFormState = {
  ...EMPTY_FORM,
  title: "  Sunny 2BHK  ",
  type: "Apartment",
  location: "Kondapur, Hyderabad",
  city: "Hyderabad",
  locality: "Kondapur",
  state: "Telangana",
  pincode: "500084",
  priceRupees: "5000000",
  propertySubtype: "standalone_apartment",
  furnishing: "semi",
  constructionStatus: "ready",
  reraApplicability: "applicable",
  reraNumber: "TS-RERA-123",
  amenities: ["parking", "lift"],
  details: {
    ...EMPTY_DETAILS,
    projectName: "Sunny Homes",
    projectAreaAcres: "4.5",
    numberOfTowers: "3",
    totalUnits: "120",
    configurations: ["2_bhk", "3_bhk"],
    unitAreaSqft: "1150",
    rateRupees: "6500",
    saleType: "new_sale",
    facing: "east",
    amenitiesDescription: PROJECT_AMENITIES,
    about: "A calm community with landscaped gardens and generous shared spaces.",
  },
  images: [new File(["image"], "a.jpg", { type: "image/jpeg" })],
  documents: [],
  meta: "Ready to move",
};

const MEDIA = [
  {
    kind: "image" as const,
    content_type: "image/jpeg" as const,
    object_key:
      "private/property-submissions/staging/00000000-0000-0000-0000-000000000001/00000000-0000-0000-0000-000000000002/asset.jpg",
    position: 0,
  },
];

describe("buildSubmissionPayload()", () => {
  it("converts rupees to integer paise (x100)", () => {
    const p = buildSubmissionPayload(VALID, MEDIA);
    expect(p.price_paise).toBe(500_000_000);
    expect(Number.isInteger(p.price_paise)).toBe(true);
  });

  it("derives the broad category from the selected property subtype", () => {
    const payload = buildSubmissionPayload(VALID, MEDIA);
    expect(payload.property_subtype).toBe("standalone_apartment");
    expect(payload.category).toBe("apartments");
  });

  it("rounds fractional rupees to whole paise", () => {
    expect(buildSubmissionPayload({ ...VALID, priceRupees: "1234.55" }, MEDIA).price_paise).toBe(123455);
  });

  it("trims strings and coerces numeric fields", () => {
    const p = buildSubmissionPayload(VALID, MEDIA);
    expect(p.title).toBe("Sunny 2BHK");
    expect(p.bhk).toBe(0);
    expect(p.area_sqft).toBe(1150);
    expect(p.age_years).toBe(0);
  });

  it("builds the closed project-residence payload", () => {
    const p = buildSubmissionPayload(VALID, MEDIA);
    expect(p.structured_details).toMatchObject({
      kind: "project_residence",
      project_name: "Sunny Homes",
      unit_or_plot_area_sqft: 1150,
      price_per_sqft_paise: 650_000,
      configurations: ["2_bhk", "3_bhk"],
    });
  });

  it("passes amenities through and omits empty optional strings as null", () => {
    const p = buildSubmissionPayload({ ...VALID, meta: "" }, MEDIA);
    expect(p.amenities).toEqual(["parking", "lift"]);
    expect(p.meta).toBeNull();
    expect(p.media).toEqual(MEDIA);
  });

  it("sends a trimmed developer name, or null when blank", () => {
    expect(buildSubmissionPayload({ ...VALID, developerName: "  My Home " }, MEDIA).developer_name).toBe("My Home");
    expect(buildSubmissionPayload({ ...VALID, developerName: "   " }, MEDIA).developer_name).toBeNull();
  });
});

describe("validateForm()", () => {
  it("accepts a complete valid form", () => {
    expect(validateForm(VALID)).toEqual({});
  });

  it.each(["", "Clubhouse and pool"])("accepts an optional project amenities description (%j)", (amenitiesDescription) => {
    const details = { ...VALID.details, amenitiesDescription };

    expect(validateForm({ ...VALID, details }).amenitiesDescription).toBeUndefined();
  });

  it("still caps project amenities at 500 words", () => {
    const details = {
      ...VALID.details,
      amenitiesDescription: Array.from({ length: 501 }, () => "landscaped").join(" "),
    };

    expect(validateForm({ ...VALID, details }).amenitiesDescription).toContain("500 words");
  });

  it("sends null when the project amenities description is blank", () => {
    const details = { ...VALID.details, amenitiesDescription: "   " };
    const p = buildSubmissionPayload({ ...VALID, details }, MEDIA);

    expect(p.structured_details).toMatchObject({ kind: "project_residence", amenities_description: null });
  });

  it("flags a non-6-digit pincode", () => {
    expect(validateForm({ ...VALID, pincode: "5008" }).pincode).toBeTruthy();
  });

  it("flags a zero or missing price", () => {
    expect(validateForm({ ...VALID, priceRupees: "0" }).priceRupees).toBeTruthy();
    expect(validateForm({ ...VALID, priceRupees: "" }).priceRupees).toBeTruthy();
  });

  it("flags an entered undivided share of zero instead of sending 0 to the API", () => {
    const details = { ...VALID.details, udsFrom: "0" };
    expect(validateForm({ ...VALID, details }).udsFrom).toBe(
      "Enter a whole number greater than 0, or leave undivided share blank.",
    );
    expect(validateForm({ ...VALID, details: { ...VALID.details, udsFrom: "" } }).udsFrom).toBeUndefined();
    expect(validateForm({ ...VALID, details: { ...VALID.details, udsFrom: "420" } }).udsFrom).toBeUndefined();
  });

  it("flags whole-number fields that would be sent as 0", () => {
    const details = { ...VALID.details, unitAreaSqft: "0.5", numberOfTowers: "0.4" };
    const errors = validateForm({ ...VALID, details });
    expect(errors.unitAreaSqft).toBe("Enter a whole number greater than 0 for unit or flat area.");
    expect(errors.numberOfTowers).toBe("Enter a whole number greater than 0 for number of towers.");
  });

  it("flags a price that rounds to zero paise", () => {
    expect(validateForm({ ...VALID, priceRupees: "0.001" }).priceRupees).toBeTruthy();
    expect(validateForm({ ...VALID, details: { ...VALID.details, rateRupees: "0.004" } }).rateRupees).toBeTruthy();
  });

  it("flags missing required text fields", () => {
    const errs = validateForm({
      ...VALID,
      title: "  ",
      propertySubtype: "",
    });
    expect(errs.title).toBeTruthy();
    expect(errs.propertySubtype).toBeTruthy();
  });

  it("accepts a blank optional RERA number", () => {
    expect(validateForm({ ...VALID, reraNumber: "" })).toEqual({});
    expect(buildSubmissionPayload({ ...VALID, reraNumber: "" }, MEDIA).rera_number).toBeNull();
  });

  it("rejects numbers and links in public narrative fields", () => {
    expect(
      validateForm({
        ...VALID,
        details: { ...VALID.details, about: "Call 9876543210" },
      }).about,
    ).toBeTruthy();
    expect(
      validateForm({
        ...VALID,
        details: { ...VALID.details, about: "Visit example.xyz" },
      }).about,
    ).toBeTruthy();
    expect(
      validateForm({
        ...VALID,
        details: { ...VALID.details, about: "Use ftp://example" },
      }).about,
    ).toBeTruthy();
  });

  it("requires managed images and rejects unsupported media", () => {
    expect(validateForm({ ...VALID, images: [] }).images).toBeTruthy();
    expect(
      validateForm({
        ...VALID,
        images: [new File(["gif"], "bad.gif", { type: "image/gif" })],
      }).images,
    ).toBeTruthy();
    expect(
      validateForm({
        ...VALID,
        documents: [new File(["text"], "note.txt", { type: "text/plain" })],
      }).documents,
    ).toBeTruthy();
    expect(
      validateForm({
        ...VALID,
        panoramas: [new File(["gif"], "tour.gif", { type: "image/gif" })],
      }).panoramas,
    ).toBeTruthy();
  });
});

describe("option lists match the backend enums", () => {
  it("furnishing and construction match the backend enums", () => {
    expect(FURNISHING_OPTIONS.map((o) => o.value).sort()).toEqual(["furnished", "semi", "unfurnished"]);
    expect(CONSTRUCTION_OPTIONS.map((o) => o.value).sort()).toEqual(["ready", "under_construction"]);
  });
});

const RENT: SubmitFormState = {
  ...VALID,
  listingIntent: "rent",
  priceRupees: "25000",
  securityDepositRupees: "150000",
  minimumLeaseMonths: "11",
  details: { ...VALID.details, saleType: "" },
};

describe("listing intent", () => {
  it("defaults a new form to a sale listing", () => {
    expect(EMPTY_FORM.listingIntent).toBe("sale");
  });

  it("accepts a rent listing with deposit and minimum term", () => {
    expect(validateForm(RENT, { requireImages: false })).toEqual({});
  });

  it("sends the rent terms and drops the sale type", () => {
    const payload = buildSubmissionPayload(RENT, []);

    expect(payload.listing_intent).toBe("rent");
    expect(payload.price_paise).toBe(2_500_000);
    expect(payload.security_deposit_paise).toBe(15_000_000);
    expect(payload.minimum_lease_months).toBe(11);
    expect(payload.structured_details).toMatchObject({ sale_type: null });
  });

  it.each([
    ["securityDepositRupees", "security deposit"],
    ["minimumLeaseMonths", "minimum lease duration"],
  ])("requires %s on a rent listing", (field, label) => {
    const errors = validateForm({ ...RENT, [field]: "" }, { requireImages: false });
    expect(errors[field]).toMatch(new RegExp(label));
  });

  it("does not require a sale type on a rent listing", () => {
    const errors = validateForm(RENT, { requireImages: false });
    expect(errors.saleType).toBeUndefined();
  });

  it("still requires a sale type on a sale listing", () => {
    const errors = validateForm(
      { ...VALID, details: { ...VALID.details, saleType: "" } },
      { requireImages: false },
    );
    expect(errors.saleType).toMatch(/Sale type/);
  });

  it("nulls the rent terms when the listing is switched back to sale", () => {
    // The author flips the toggle back without clearing the deposit they typed.
    // The payload must not carry it, or the API rejects the whole submission.
    const payload = buildSubmissionPayload({ ...RENT, listingIntent: "sale" }, []);

    expect(payload.security_deposit_paise).toBeNull();
    expect(payload.minimum_lease_months).toBeNull();
    expect(payload.available_from).toBeNull();
  });
});

describe("listing links", () => {
  it("omits the field entirely when no link was entered", () => {
    expect(buildSubmissionPayload({ ...VALID, listingLinks: ["", "  "] }, []).listing_links).toBeNull();
  });

  it("sends only the URL and lets the server derive the platform", () => {
    const payload = buildSubmissionPayload(
      { ...VALID, listingLinks: [" https://youtu.be/abc ", ""] },
      [],
    );

    expect(payload.listing_links).toEqual([{ url: "https://youtu.be/abc" }]);
  });

  it("reports an off-allowlist link against its own row", () => {
    const errors = validateForm(
      { ...VALID, listingLinks: ["https://youtu.be/abc", "https://phish.example/x"] },
      { requireImages: false },
    );

    expect(errors["listingLink-0"]).toBeUndefined();
    expect(errors["listingLink-1"]).toMatch(/YouTube, Instagram, or Facebook/);
  });

  it("rejects more than four links", () => {
    const errors = validateForm(
      {
        ...VALID,
        listingLinks: Array.from({ length: 5 }, (_, index) => `https://youtu.be/abc${index}`),
      },
      { requireImages: false },
    );

    expect(errors.listingLinks).toMatch(/at most 4/);
  });
});

describe("submissionIssuesToFieldErrors()", () => {
  it("puts API validation errors on the form field they belong to", () => {
    expect(
      submissionIssuesToFieldErrors([
        { field: "structured_details.project_residence.uds_sqft", message: "Input should be greater than 0" },
        { field: "price_paise", message: "Input should be greater than 0" },
        { field: "structured_details.plot.price_per_sqyd_paise", message: "Input should be greater than 0" },
      ]),
    ).toEqual({
      udsFrom: "Input should be greater than 0",
      priceRupees: "Input should be greater than 0",
      rateRupees: "Input should be greater than 0",
    });
  });

  it("ignores issues it cannot place, so the caller can fall back to a toast", () => {
    expect(submissionIssuesToFieldErrors([{ field: "media.0.object_key", message: "bad" }])).toEqual({});
    expect(submissionIssuesToFieldErrors(undefined)).toEqual({});
  });
});

describe("listing form refinements (CS-018)", () => {
  it("sends the unit or flat area and undivided share as From-To ranges", () => {
    const details = {
      ...VALID.details,
      unitAreaMaxSqft: "1450",
      udsFrom: "40",
      udsTo: "60",
      udsUnit: "sqyd",
      configurations: ["2_5_bhk", "3_5_bhk"],
    };
    const p = buildSubmissionPayload({ ...VALID, details }, MEDIA);
    expect(p.structured_details).toMatchObject({
      unit_or_plot_area_sqft: 1150,
      unit_or_plot_area_max_sqft: 1450,
      uds_sqft: null,
      uds_area_from: 40,
      uds_area_to: 60,
      uds_area_unit: "sqyd",
      configurations: ["2_5_bhk", "3_5_bhk"],
    });
  });

  it("sends no undivided share fields when it is left blank", () => {
    const p = buildSubmissionPayload(VALID, MEDIA);
    expect(p.structured_details).toMatchObject({
      uds_area_from: null,
      uds_area_to: null,
      uds_area_unit: null,
    });
  });

  it("checks the To values against From", () => {
    expect(
      validateForm({ ...VALID, details: { ...VALID.details, unitAreaMaxSqft: "900" } }).unitAreaMaxSqft,
    ).toBe("The unit or flat area To value must not be less than From.");
    expect(
      validateForm({ ...VALID, details: { ...VALID.details, udsFrom: "60", udsTo: "40" } }).udsTo,
    ).toBe("The undivided share To value must not be less than From.");
    expect(
      validateForm({ ...VALID, details: { ...VALID.details, udsTo: "40" } }).udsFrom,
    ).toBe("Enter the undivided share From value before To.");
  });

  it("uses a predefined authority or the typed Other name", () => {
    const predefined = buildSubmissionPayload(
      { ...VALID, details: { ...VALID.details, approvalAuthority: "HMDA", approvalReference: "LP/12/2024" } },
      MEDIA,
    );
    expect(predefined.structured_details).toMatchObject({
      local_approval: { authority: "HMDA", reference_number: "LP/12/2024" },
    });
    const other = { ...VALID.details, approvalAuthority: "other", approvalAuthorityOther: "  GVMC " };
    expect(buildSubmissionPayload({ ...VALID, details: other }, MEDIA).structured_details).toMatchObject({
      local_approval: { authority: "GVMC" },
    });
    expect(
      validateForm({ ...VALID, details: { ...VALID.details, approvalAuthority: "other" } }).approvalAuthorityOther,
    ).toBe("Enter the approval authority.");
  });

  it("only sends a RERA number when RERA applies", () => {
    expect(buildSubmissionPayload(VALID, MEDIA).rera_number).toBe("TS-RERA-123");
    expect(
      buildSubmissionPayload({ ...VALID, reraApplicability: "exemption_claimed" }, MEDIA).rera_number,
    ).toBeNull();
  });

  it("allows short numbers in descriptions but not phone numbers", () => {
    const about = "Three towers with 450 homes, ready by 2027.";
    expect(validateForm({ ...VALID, details: { ...VALID.details, about } }).about).toBeUndefined();
    for (const phone of ["Call 9876543210", "Call 98765 43210", "Call +91-98765-43210"]) {
      expect(validateForm({ ...VALID, details: { ...VALID.details, about: phone } }).about).toContain(
        "up to 6 digits",
      );
    }
  });

  it("accepts AVIF photos and up to ten 360 images", () => {
    const avif = new File(["avif"], "front.avif", { type: "image/avif" });
    expect(validateForm({ ...VALID, images: [avif] }).images).toBeUndefined();
    const pano = (name: string) => new File(["png"], name, { type: "image/png" });
    const ten = Array.from({ length: 10 }, (_, index) => pano(`p${index}.png`));
    expect(validateForm({ ...VALID, panoramas: ten }).panoramas).toBeUndefined();
    expect(validateForm({ ...VALID, panoramas: [...ten, pano("p10.png")] }).panoramas).toBe(
      "Choose at most 10 360 images.",
    );
  });

  it("loads a legacy single undivided share and a free-typed authority for editing", () => {
    const submission = {
      ...buildSubmissionPayload(VALID, MEDIA),
      listing_intent: "sale",
      rera_applicability: "applicable",
      rera_number: "TS-RERA-123",
      structured_details: {
        ...buildSubmissionPayload(VALID, MEDIA).structured_details,
        uds_sqft: 420,
        uds_area_from: null,
        uds_area_to: null,
        uds_area_unit: null,
        local_approval: { authority: "Gram Panchayat Kondapur", reference_number: null },
      },
    } as unknown as Parameters<typeof submissionToFormState>[0];
    const form = submissionToFormState(submission);
    expect(form.details.udsFrom).toBe("420");
    expect(form.details.udsUnit).toBe("sqft");
    expect(form.details.approvalAuthority).toBe("other");
    expect(form.details.approvalAuthorityOther).toBe("Gram Panchayat Kondapur");
  });
});
