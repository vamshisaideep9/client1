# Data sources

Reference data committed under `apps/api/app/data/`. Each entry records where
the data came from, its licence and attribution, what was changed, and how to
rebuild it. Update the entry (and its checksum) whenever a file changes; the
API test suite compares the checksum below with the committed file.

## `pincodes.csv.gz` — India pincodes, place names and centroids

- **Used for:** the `pincodes` reference table (CS-026). It turns a profile
  pincode into a place name (area, district, state), maps a one-time GPS
  position to the nearest pincode, and gives location-targeted campaigns a
  pincode centroid. It holds no personal data.
- **Source:** GeoNames postal-code extract for India,
  <https://download.geonames.org/export/zip/IN.zip> (`IN.txt`, tab-separated:
  country code, postal code, place name, state, state code, district, district
  code, sub-district, sub-district code, latitude, longitude, accuracy).
- **Retrieved:** 2026-11-17. Server `Last-Modified: Mon, 16 Nov 2026 04:02:11
  GMT`; `IN.zip` SHA-256
  `9d607ef61aa5db67212ade52b009b7e856d38584eb19d25a7729fbbeb6c6db5e`
  (155,570 office rows, 19,238 distinct pincodes).
- **Licence:** Creative Commons Attribution 4.0 International (CC BY 4.0),
  <https://creativecommons.org/licenses/by/4.0/>, as stated in the GeoNames
  postal-code `readme.txt` shipped in the archive. GeoNames provides the data
  "as is", without warranty of accuracy, timeliness or completeness.
- **Attribution (required):** "Pincode place names and locations: GeoNames
  (www.geonames.org), CC BY 4.0." The web app shows this credit beside the
  pincode field and in the privacy notice.
- **Why not data.gov.in:** the Department of Posts "All India Pincode Directory"
  (Government Open Data License – India) was the first choice, but its file
  could not be fetched without an API key on 2026-11-17 (direct file URL
  answered 403). Revisit if a keyless download becomes available.
- **Changes made (CC BY 4.0 asks for them to be indicated):** reduced to one
  row per pincode by `scripts/build_pincode_reference.py`:
  - kept only `IN` rows whose code is a valid Indian pincode (six digits,
    first digit 1–9);
  - state = the state most of the pincode's offices are in; district = the
    most common district within it;
  - area = the head-office / GPO name without its suffix, else an office named
    like its sub-district, else the most common sub-district, else the first
    office name alphabetically;
  - centroid = mean of the coordinates inside India's bounding box (latitude
    6.0–37.6, longitude 68.0–97.6), using only the most precise GeoNames
    accuracy class present for that pincode; a pincode with no usable
    coordinate keeps its place name with empty coordinates (none in this
    build);
  - text trimmed, control and replacement characters removed, lengths capped
    to the column sizes; names are otherwise as published (for example
    "Pondicherry", "Jammu & Kashmir", older district names).
- **Output:** 19,238 pincodes, all with a centroid; 212,551 bytes gzip
  (about 1.0 MB as CSV). SHA-256
  `4947fb4eff53bec03a72aaa4e5cabec54f7ea77098f16df7c55703724f3cd93c`.
- **Known limits:** GeoNames coordinates are estimates (accuracy class 1 is
  derived from neighbouring codes) and can be tens of kilometres off, so
  "Use my location" suggests a pincode the person confirms before saving; it
  never saves one on its own. District names follow the source and can predate
  recent district reorganisations.
- **Rebuild:** download `IN.zip` into a new empty directory, extract it, then
  from the repository root run
  `python -I scripts/build_pincode_reference.py <dir>/IN.txt apps/api/app/data/pincodes.csv.gz`
  (deterministic output). Refresh the table in an existing database with a new
  migration that re-runs the idempotent upsert used by
  `e5a7c9b1d3f6_pincode_reference_and_profile_pincode.py`.
