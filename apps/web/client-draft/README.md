# Public client draft

Run `pnpm export:client` from `apps/web`. Open
`build/client-draft/Dhanadhara-Client-Draft.html` from the repository root directly
in a browser, or run `pnpm preview:client` for a loopback preview on port 3001.
Share the HTML file itself; it contains its CSS, JavaScript, images and fonts.
JavaScript must be enabled. The browser does not need an internet connection.

The export reuses the public React pages and all 18 calculator engines. Small
build-only adapters replace Next routing, image loading, filesystem artwork
lookup, and public catalogue reads. Hash routes preserve navigation, filters,
calculator inputs and browser history. The compiler comes from the existing
locked Vitest/Vite toolchain; no additional dependencies or remote assets are
downloaded. An existing Next build supplies Geist; otherwise the bundled Space
Grotesk font is used for both text roles.

The HTML retains bundled JavaScript notices and embeds the fonts' OFL notices.
Geist's notice is from `vercel/geist-font/OFL.txt`, Git blob
`04e95fc550855eb44416b9db1f6722f5cb7342db` (retrieved 2026-10-12).

`data.ts` contains explicit illustrative service/provider/property content and
the previously approved sponsor artwork and copy. These fixtures never enter
the Next application. `site.ts` keeps unconfirmed contact information labelled
as such. Do not insert account data, credentials, private exports or real
customer documents. The exporter does not load environment files.

Accounts, dashboards and token-specific invitations are outside this public
draft. Their links explain that the live application is required. Enquiry forms
and partner-intake layouts can be reviewed, but submissions, OTPs, document
uploads and external links are inactive. No submission success is simulated.
CSV and Excel calculator downloads work locally. A noindex directive and an
offline-only CSP apply to the document; it is a review artifact, not a deployment.

Verification:

```sh
pnpm export:client
pnpm exec playwright test --config playwright.client-draft.config.ts
```

The browser tests open the actual `file://` artifact with networking disabled,
check every included public route, image failures, sponsor rendering, calculator
inputs/exports, mobile navigation, history, and truthful form behaviour.

For the normal application, `pnpm dev` still requires a running API. Native
development defaults to `http://localhost:8000`; Docker and deployed runtimes
can supply `API_INTERNAL_URL`, and production retains `http://api:8000` as its
default. A stopped backend remains a real error and is not replaced with fixtures.
