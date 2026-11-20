# Agent lead intake review evidence

Synthetic fixtures only. These screenshots were captured from the Node 22 Alpine
production standalone server for runtime candidate `2010d74a`, using
`e2e/agent-lead-intake.spec.ts` and the embedded commission case in
`e2e/admin-financial-products.spec.ts`. They contain no customer data. Screenshots are
review evidence, rather than pixel baselines or proof of a live API integration.

| View | Width | Evidence |
| --- | --- | --- |
| Loans Agent: contact and selected product | 390px | [Form](agent-loan-form-390.png) |
| Real Estate Agent: subtype with optional listing | 768px | [Form](agent-property-form-768.png) |
| Bulk results with invalid and repeated rows | 320px | [Results](bulk-results-320.png) |
| Admin: immediate rate entry without a checker | 1440px | [Rates](admin-rates-1440.png) |
| Sub Admin: proposal awaiting review | 390px | [Rates](subadmin-rates-390.png) |
| Product workspace: saved commission after an error and retry | 390px | [Commission](product-agent-commission-390.png) |

Fresh terminal verification for the unchanged runtime candidate:

- `pnpm lint` and `pnpm typecheck`: exit 0.
- `pnpm test`: exit 0, 153 files and 1,113 tests passed.
- `pnpm build` in Node 22 Alpine: exit 0, all 118 pages generated.
  All eight production font hashes match the prior verified artifact.
- `pnpm test:e2e e2e/agent-lead-intake.spec.ts` against the production bundle:
  exit 0, all ten scenarios passed. API responses are explicitly mocked.
- After the API's final permission/audit correction, the three affected fixtures
  were aligned and rerun: all three passed on the unchanged production artifact,
  with fresh fixture lint/typecheck. The Agent fixture uses only its DTO fields;
  pending proposals have no review identity; direct Admin entry has no checker
  and visibly updates the approved rate. These repeat existing scenarios.
- The same standalone artifact passes the additional embedded product-commission
  scenario: a failed save keeps rate and note, retry succeeds, and no product
  update is sent. The unrelated Save product action is absent on this tab.
  The first follow-up test expected an internal 503 detail; it now correctly
  asserts the client's deliberately generic retry error. Runtime behavior did
  not change for that test correction.
- New and neighboring browser journeys have 36 distinct passing scenarios across
  segmented development/production runs. A prior combined run failed two checks;
  the 320px Edit reachability issue and the public-navigation test wait were
  corrected and the affected checks passed. This is not a claim that one final
  combined 36-test run passed.

The design review retains the existing dashboard colors, fonts, spacing and
Radix controls. Mobile results remain readable without horizontal scrolling.
No additional motion or dependency was introduced. Security review covers
hidden-note ownership on email-only edits, formula-safe CSV results, bounded
spreadsheet parsing and generated contract consumers. The API remains the
authorization boundary; database-backed behavior is verified in the parent API
slice.
