# Ground truth provenance — Lexington (task 0.1)

Assembled 2026-06-11 by agent-proxy from **captured real catalogs and live
fetches** (not from any pipeline output). ⚠️ Flagged for a human review pass —
especially the zero-row providers below. Rebuild the deterministic portion with
`python -m scripts.build_ground_truth`.

234 rows. Per-provider sources:

| Provider | Rows | Source |
|---|---|---|
| lexingtoncommunityed.org | 129 | Live WooCommerce store API (`wp-json/wc/store/products`), weeks one–six; captured to `tests/fixtures/communityed/store_products.json`. `/class/{slug}` permalink = info page. After-school-care items excluded. |
| jwhayden.org | 40 | Captured WebTrac catalogs (`tests/fixtures/webtrac/*.meta.json`): per-FMID name+dates; iteminfo URL = info page. |
| lexrecma.myrec.com | 26 | Captured MyRec listing (`tests/fixtures/myrec/*.meta.json`); youth-summer subset hand-selected from the 89-program catalog (selection list in `scripts/build_ground_truth.py`); program_details URL = info page. |
| therobohub.com | 15 | Live marketing page headings paired with Sawyer activity-set links (saved to `tests/fixtures/sawyer/therobohub.com.html`). |
| vikingcamps.com | 6 | Live page: summer camp categories (vacation/holiday camps excluded as off-season). |
| hancocknurseryschool.org | 5 | Live page: "HNS Summer", ages 3-5, sessions 1–5 with dates, $330/session. (Old pipeline fabricated 2 fake camps here.) |
| lexingtonunited.org | 3 | Live page: June Kick-Off / July Mid-Summer / August Preseason clinics (April Vacation excluded as off-season). |
| summersedgedaycamp.com | 2 | Live page: Day Camp + Tennis School (CampBrain registration sits behind queue-it). |
| lexingtonplaycarecenter.org | 2 | Live page: "Camp LPC" + "Big Kid Camp" (July/August). |
| others (waldorf, lexfarm, fuse, debate, goddard, munroe) | 1 each | Live pages: single umbrella summer program each. Munroe's 2026 per-week list "online December 10" — enrich after ACTIVE API capture (task 3.6). |

## Deliberately zero rows (do NOT count against recall without review)

| Provider | Why |
|---|---|
| lexingtonsymphony.org | Phoenix Project is explicitly a camp **for adults** — correct GT is zero youth rows (precision test: old pipeline published 3 junk rows here). |
| lca.edu | 403 bot-blocked on plain fetch — needs human/rendered review. |
| ussportscamps.com | JS search page ("1 basketball camp near Lexington") — needs human confirm of the camp + venue. |
| massgeneral.org (Aspire) | Apply page doesn't enumerate programs; Aspire summer programs exist — needs human enumeration. |
| massaudubon.org (Drumlin Farm) | Sanctuary page links "Nature Camps" without enumerating; also geo-review (Lincoln, MA). |

## Second town (task 0.2) — burlington.csv

Program-level, lower fidelity, from the frozen Burlington provider set; includes
vendors Lexington lacks (SGA/Daxko YMCA portals). Needs the same human pass.
