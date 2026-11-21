import { describe, expect, it } from "vitest";

import {
  enquiryRecord,
  fieldVisibilityConfigRecord,
  financialServiceEnquiryRecord,
  siteVisitRecord,
} from "./operational-records-view";

describe("property enquiry and site visit operational records", () => {
  it("leads an enquiry with when the client submitted it", () => {
    const record = enquiryRecord({
      id: "11111111-1111-4111-8111-111111111111",
      title: "3BHK Villa",
      locality: "Whitefield",
      city: "Bengaluru",
      property_ref: "22222222-2222-4222-8222-222222222222",
      status: "new",
      user_uuid: "33333333-3333-4333-8333-333333333333",
      created_at: "2026-11-14T08:45:00Z",
      updated_at: "2026-11-14T08:45:00Z",
    });

    expect(record.fields[0].label).toBe("Submitted on");
    expect(record.fields[0].value).toMatch(/2026/);
    expect(record.fields[0].value).toMatch(/\d{1,2}:\d{2}/);
    expect(record.fields.map((field) => field.label)).not.toContain("Created");
  });

  it("keeps a site visit's submission time apart from the visit slot", () => {
    const record = siteVisitRecord({
      id: "44444444-4444-4444-8444-444444444444",
      title: "3BHK Villa",
      locality: "Whitefield",
      city: "Bengaluru",
      property_ref: "22222222-2222-4222-8222-222222222222",
      status: "requested",
      user_uuid: "33333333-3333-4333-8333-333333333333",
      preferred_date: "2026-11-20",
      preferred_time_slot: "morning",
      cancelled_at: null,
      created_at: "2026-11-14T08:45:00Z",
      updated_at: "2026-11-14T08:45:00Z",
    });

    expect(record.fields.map((field) => field.label).slice(0, 2)).toEqual([
      "Submitted on",
      "Visit on",
    ]);
    expect(record.fields[0].value).toMatch(/\d{1,2}:\d{2}/);
    expect(record.fields.map((field) => field.label)).not.toContain("Requested");
  });
});

describe("field visibility operational records", () => {
  it("projects policy metadata without adding an edit action", () => {
    const record = fieldVisibilityConfigRecord({
      id: "805ba7c0-d0f8-4461-8296-617fa19efbc7",
      target_role: "employee",
      entity: "lead",
      field_key: "name",
      mode: "deny",
      updated_at: "2026-09-01T09:30:00Z",
    });

    expect(record.id).toBe("805ba7c0-d0f8-4461-8296-617fa19efbc7");
    expect(record.title).toBe("Lead Name");
    expect(record.subtitle).toBe("Officer / Lead policy");
    expect(record.status).toBe("Deny");
    expect(record.fields.map((field) => field.label)).toEqual([
      "Field key",
      "Last updated",
    ]);
  });
});

describe("financial service enquiry operational records", () => {
  it("projects public workflow metadata without applicant or form details", () => {
    const record = financialServiceEnquiryRecord({
      id: "f04ceace-aa51-44b6-a7ee-8d52b7fe7b17",
      product_label: "Operations credit card",
      product_category: "credit_card",
      status: "submitted",
      form_version: 7,
      submitted_at: "2026-09-02T09:30:00Z",
    });

    expect(record.id).toBe("f04ceace-aa51-44b6-a7ee-8d52b7fe7b17");
    expect(record.title).toBe("Operations credit card");
    expect(record.subtitle).toBe("Credit Card enquiry");
    expect(record.status).toBe("Submitted");
    expect(record.fields.map((field) => field.label)).toEqual([
      "Form version",
      "Submitted",
    ]);
  });
});
