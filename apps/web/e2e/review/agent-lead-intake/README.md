# Agent lead intake review evidence

Synthetic fixtures only. These screenshots were captured from the Node 22 Alpine
production standalone server for runtime candidate `e48d19f0`, using
`e2e/agent-lead-intake.spec.ts`. They contain no customer data. Screenshots are
review evidence, rather than pixel baselines or proof of a live API integration.

| View | Width | Evidence |
| --- | --- | --- |
| Loans Agent: contact and approved commission | 390px | [Form](agent-loan-form-390.png) |
| Real Estate Agent: subtype with optional listing | 768px | [Form](agent-property-form-768.png) |
| Bulk results with invalid and repeated rows | 320px | [Results](bulk-results-320.png) |
| Admin: rate approval and immediate entry | 1440px | [Rates](admin-rates-1440.png) |
| Sub Admin: proposal awaiting review | 390px | [Rates](subadmin-rates-390.png) |

Fresh terminal verification for the unchanged runtime candidate:

- `pnpm lint` and `pnpm typecheck`: exit 0.
- `pnpm test`: exit 0, 153 files and 1,113 tests passed.
- `pnpm build` in Node 22 Alpine: exit 0, all 118 pages generated.
- `pnpm test:e2e e2e/agent-lead-intake.spec.ts` against the production bundle:
  exit 0, all ten scenarios passed. API responses are explicitly mocked.
- Standalone server: Excel upload smoke passed, followed by five screenshot
  journeys at the widths above, all exit 0.
- New and neighboring development-browser journeys have 35 distinct passing
  scenarios across segmented runs. A prior combined run failed two checks;
  the 320px Edit reachability issue and the public-navigation test wait were
  corrected and the affected checks passed. This is not a claim that one final
  combined 35-test run passed.

The design review retains the existing dashboard colors, fonts, spacing and
Radix controls. Mobile results remain readable without horizontal scrolling.
No additional motion or dependency was introduced. Security review covers
hidden-note ownership on email-only edits, formula-safe CSV results, bounded
spreadsheet parsing and generated contract consumers. The API remains the
authorization boundary; database-backed behavior is verified in the parent API
slice.
