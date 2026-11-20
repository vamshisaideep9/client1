"use client";

import * as React from "react";
import { Info, MapPin } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PropertySelect } from "@/features/real-estate/property-select";
import { useProperties } from "@/features/real-estate/use-properties";
import { getPublicProviderOffersClient } from "@/lib/financial-catalog-client";
import type { PublicProviderOfferList } from "@/lib/financial-catalog";
import { formatPaise } from "@/lib/format";
import { getLoanTypes, type LoanTypeOption } from "@/lib/loans";
import { rows as detailRows } from "@/lib/property-details";
import type { REListing } from "@/lib/real-estate";
import { PROPERTY_SUBTYPE_OPTIONS, type PropertySubtype } from "@/lib/property-taxonomy";
import { getAgentCommissionRates, type AgentCommissionRate } from "@/lib/commission-rates-api";
import { commissionRateLabel } from "@/lib/commission-rate";

export type LeadInterest =
  | { kind: "property"; propertyId?: string; propertyType?: PropertySubtype }
  | { kind: "product"; productSlug: string }
  | null;

const FEE_LABEL = /price|fee|charge|maintenance|deposit|booking|cost/i;

function PropertyFeeDetails({ listing }: { listing: REListing }) {
  const facts = listing.structuredDetails
    ? detailRows(listing.structuredDetails).filter(
        (row) => FEE_LABEL.test(row.label) && row.value != null && row.value !== "",
      )
    : [];
  return (
    <div className="grid gap-4">
      <div>
        <p className="font-semibold text-text-primary">{listing.title}</p>
        <p className="flex items-center gap-1 text-sm text-text-secondary">
          <MapPin className="h-3.5 w-3.5" aria-hidden />
          {listing.location}
        </p>
        <p className="mt-1 text-xs text-text-secondary">
          {listing.type}
          {listing.bhk ? ` · ${listing.bhk} BHK` : ""}
          {listing.areaSqft ? ` · ${listing.areaSqft.toLocaleString("en-IN")} sq ft` : ""}
        </p>
      </div>
      <dl className="grid gap-2 rounded-xl bg-surface p-4 text-sm">
        <div className="flex justify-between gap-3">
          <dt className="text-text-secondary">{listing.listingIntent === "rent" ? "Rent" : "Price"}</dt>
          <dd className="font-semibold text-text-primary">{listing.price}</dd>
        </div>
        {listing.securityDepositPaise != null ? (
          <div className="flex justify-between gap-3">
            <dt className="text-text-secondary">Security deposit</dt>
            <dd className="font-semibold text-text-primary">{formatPaise(listing.securityDepositPaise)}</dd>
          </div>
        ) : null}
        {facts.map((row) => (
          <div key={row.label} className="flex justify-between gap-3">
            <dt className="text-text-secondary">{row.label}</dt>
            <dd className="text-right font-semibold text-text-primary">{String(row.value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function ProductFeeDetails({ product }: { product: LoanTypeOption }) {
  const [offers, setOffers] = React.useState<PublicProviderOfferList | null>(null);
  const [failed, setFailed] = React.useState(false);
  const [rate, setRate] = React.useState<AgentCommissionRate | null>(null);
  const [rateState, setRateState] = React.useState<"loading" | "ready" | "error">("loading");
  const [attempt, setAttempt] = React.useState(0);

  React.useEffect(() => {
    let active = true;
    void getAgentCommissionRates().then((res) => {
      if (!active) return;
      setRateState(res.ok ? "ready" : "error");
      if (res.ok) setRate(res.data.rates[product.name] ?? null);
    });
    return () => { active = false; };
  }, [product.name, attempt]);

  React.useEffect(() => {
    let active = true;
    void getPublicProviderOffersClient(product.name, { pageSize: 5 }).then((res) => {
      if (!active) return;
      if (res.ok) setOffers(res.data);
      else setFailed(true);
    });
    return () => {
      active = false;
    };
  }, [product.name]);

  return (
    <div className="grid gap-3">
      <p className="font-semibold text-text-primary">{product.label}</p>
      <div className="rounded-xl border border-border p-3 text-sm" aria-live="polite">
        {rateState === "loading" ? "Loading your commission…" : rateState === "error" ? (
          <><p>Could not load the commission rate.</p><Button variant="outline" size="sm" onClick={() => { setRateState("loading"); setAttempt((n) => n + 1); }}>Retry rate</Button></>
        ) : rate ? (
          <><p className="font-semibold">Your commission: {commissionRateLabel(rate)}</p>{rate.note ? <p className="mt-1 text-text-secondary">{rate.note}</p> : null}</>
        ) : <p>No approved commission rate for this product yet.</p>}
      </div>
      {offers === null && !failed ? (
        <p className="text-sm text-text-secondary">Loading provider terms…</p>
      ) : offers && offers.items.length > 0 ? (
        <ul className="grid gap-2 text-sm">
          {offers.items.map((offer) => (
            <li key={offer.id} className="rounded-xl bg-surface p-3">
              <p className="font-medium text-text-primary">
                {offer.provider.name} · {offer.offer_name}
              </p>
              <p className="text-text-secondary">
                Rate:{" "}
                {offer.min_interest_rate !== null
                  ? `${offer.min_interest_rate}%${offer.max_interest_rate !== null ? ` - ${offer.max_interest_rate}%` : "+"}`
                  : "Ask us"}
                {" · "}Processing fee: {offer.processing_fee_text ?? "Provider assessed"}
              </p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-text-secondary">
          No provider terms are published for this product yet. Fees are confirmed by the lender.
        </p>
      )}
    </div>
  );
}

// Separate so only a real-estate Agent fetches the property catalog.
function PropertyInterestSelect({
  value,
  onPick,
  propertyType,
}: {
  value: string;
  onPick: (listing: REListing) => void;
  propertyType?: PropertySubtype;
}) {
  const { listings, loading } = useProperties();
  return (
    <PropertySelect
      id="lead-interest-property"
      properties={listings.filter((listing) => !propertyType || !listing.propertySubtype || listing.propertySubtype === propertyType)}
      value={value}
      disabled={loading}
      onChange={(id) => {
        const listing = listings.find((item) => item.id === id);
        if (listing) onPick(listing);
      }}
    />
  );
}

// "What are they interested in?" for Introduce Lead. A real-estate Agent picks
// a published property and a loans Agent picks a product; picking opens a
// summary with the item's details and fees before it is attached. The API
// re-validates the choice against the Agent's business line, so this is a
// convenience, not a permission boundary.
export function LeadInterestPicker({
  businessLine,
  value,
  onChange,
}: {
  businessLine: "loans" | "real_estate" | null;
  value: LeadInterest;
  onChange: (next: LeadInterest) => void;
}) {
  const [products, setProducts] = React.useState<LoanTypeOption[]>([]);
  const [pendingProperty, setPendingProperty] = React.useState<REListing | null>(null);
  const [pendingProduct, setPendingProduct] = React.useState<LoanTypeOption | null>(null);

  React.useEffect(() => {
    if (businessLine !== "loans") return;
    let active = true;
    void getLoanTypes().then((res) => {
      // The API already returns only active, configured products.
      if (active && res.ok) setProducts(res.data);
    });
    return () => {
      active = false;
    };
  }, [businessLine]);

  if (businessLine === null) return null;

  const open = pendingProperty !== null || pendingProduct !== null;
  function close() {
    setPendingProperty(null);
    setPendingProduct(null);
  }
  function confirm() {
    if (pendingProperty) onChange({ kind: "property", propertyId: pendingProperty.id, propertyType: pendingProperty.propertySubtype ?? (value?.kind === "property" ? value.propertyType : undefined) });
    if (pendingProduct) onChange({ kind: "product", productSlug: pendingProduct.name });
    close();
  }

  return (
    <div className="grid gap-2">
      {businessLine === "real_estate" ? (
        <>
          <Label htmlFor="lead-interest-type">Property type (optional)</Label>
          <Select value={value?.kind === "property" ? value.propertyType ?? "" : ""}
            onValueChange={(propertyType) => onChange({ kind: "property", propertyType: propertyType as PropertySubtype })}>
            <SelectTrigger id="lead-interest-type" className="w-full"><SelectValue placeholder="Choose a property type" /></SelectTrigger>
            <SelectContent>{PROPERTY_SUBTYPE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
            ))}</SelectContent>
          </Select>
          <Label htmlFor="lead-interest-property">Property (optional)</Label>
          <PropertyInterestSelect
            value={value?.kind === "property" ? value.propertyId ?? "" : ""}
            propertyType={value?.kind === "property" ? value.propertyType : undefined}
            onPick={setPendingProperty}
          />
        </>
      ) : (
        <>
          <Label htmlFor="lead-interest-product">Loan product (optional)</Label>
          <Select
            value={value?.kind === "product" ? value.productSlug : ""}
            onValueChange={(slug) => {
              const product = products.find((item) => item.name === slug) ?? null;
              if (product) setPendingProduct(product);
            }}
          >
            <SelectTrigger id="lead-interest-product" className="w-full">
              <SelectValue placeholder="Choose a product" />
            </SelectTrigger>
            <SelectContent>
              {products.map((product) => (
                <SelectItem key={product.id} value={product.name}>
                  {product.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </>
      )}
      {value ? (
        <Button type="button" variant="ghost" size="sm" className="w-fit" onClick={() => onChange(null)}>
          Remove selection
        </Button>
      ) : null}

      <Dialog open={open} onOpenChange={(next) => (next ? null : close())}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{pendingProperty ? "Property details" : "Product details"}</DialogTitle>
            <DialogDescription>Check the details and fees before attaching this to the lead.</DialogDescription>
          </DialogHeader>
          {pendingProperty ? <PropertyFeeDetails listing={pendingProperty} /> : null}
          {pendingProduct ? <ProductFeeDetails product={pendingProduct} /> : null}
          <p className="flex gap-2 rounded-xl border border-border p-3 text-xs text-text-secondary">
            <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            Your commission is agreed per deal and entered by Admin when the deal completes. Final
            prices and fees are confirmed by the seller or lender.
          </p>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              Cancel
            </Button>
            <Button type="button" onClick={confirm}>
              Attach to lead
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
