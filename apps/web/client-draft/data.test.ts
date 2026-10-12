import { describe, expect, it, vi } from "vitest";
import { draftResponse, products, properties } from "./data";
import { apiRequest } from "./api";

describe("public client draft boundary", () => {
  it("contains the full service directory and every property category", () => {
    expect(products).toHaveLength(16);
    expect(new Set(products.map(product => product.slug)).size).toBe(16);
    expect(new Set(properties.map(property => property.category))).toEqual(new Set(["apartments", "houses", "villas", "plots", "commercial"]));
  });
  it("preserves catalogue filtering and pagination", () => {
    const response = draftResponse("/api/v1/public/financial-products?category=insurance&page_size=2&page=2");
    expect(response.status).toBe(200);
    expect(response.data).toMatchObject({ total: 4, page: 2, page_size: 2 });
    expect((response.data as { items: unknown[] }).items).toHaveLength(2);
  });
  it("does not turn unknown or private endpoints into successful fixtures", () => {
    for (const path of ["/api/v1/me", "/api/v1/admin/users", "/api/v1/public/financial-products/missing"]) expect(draftResponse(path).status).toBe(404);
  });
  it("never submits data or claims a successful submission", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    try { expect(await apiRequest()).toMatchObject({ ok: false, status: 0 }); expect(fetch).not.toHaveBeenCalled(); }
    finally { fetch.mockRestore(); }
  });
});
