# Test Execution Report — SCRUM-103: Product Catalog and Sorting

**Run-ID:** 20261004-181919-saucedemo
**App:** SauceDemo (Swag Labs)
**Base URL:** https://www.saucedemo.com (page under test: `/inventory.html`)
**Date:** 2026-10-04
**Story:** SCRUM-103 — Product Catalog and Sorting
**Credentials:** `standard_user` / `secret_sauce` (seed logs in and lands on `/inventory.html`)

---

## 1. Executive Summary

| | |
|---|---|
| Acceptance criteria | 5 (AC1–AC5) |
| Test cases planned | 13 scenarios (5 suites) |
| Automated tests implemented | 16 (`*.spec.ts`) |
| Browser projects | 4 (chromium, firefox, webkit, mobile-chrome) |
| Total automated executions | 64 (16 × 4) |
| Manual exploratory scenarios | 5 (one per AC) |
| **Overall status** | ✅ **PASS** |
| Open defects | 0 |
| Skipped / blocked | 0 |

Every acceptance criterion was validated both manually (Step 3 exploratory testing) and by automated Playwright tests. All 64 automated executions pass across all four browser projects. No functional defects were found.

---

## 2. Manual Test Results (Step 3 — Exploratory Testing)

Executed from the seed session (logged in on `/inventory.html`) using Playwright MCP browser tools.

| AC | Scenario | Result | Evidence |
|---|---|---|---|
| AC1 | Products page lists exactly 6 products, each with image, name, description, price and "Add to cart" | ✅ Pass | `evidence/SCRUM-103-01-catalog-default.png` |
| AC2 | Sort dropdown defaults to "Name (A to Z)"; list alphabetical | ✅ Pass | `evidence/SCRUM-103-01-catalog-default.png` |
| AC3 | All 4 sort options (`az`/`za`/`lohi`/`hilo`) reorder list; `active-option` reflects choice | ✅ Pass | verified via live reads (see below) |
| AC4 | Add → button "Remove" + badge "1"; state survives re-sort; Remove → badge disappears at 0 | ✅ Pass | `evidence/SCRUM-103-02-add-to-cart-badge.png` |
| AC5 | Clicking a product name (and image) opens its detail page `/inventory-item.html?id=<n>` | ✅ Pass | `evidence/SCRUM-103-03-product-detail.png` |

**Catalog confirmed (AC1):** Sauce Labs Backpack $29.99, Sauce Labs Bike Light $9.99, Sauce Labs Bolt T-Shirt $15.99, Sauce Labs Fleece Jacket $49.99, Sauce Labs Onesie $7.99, Test.allTheThings() T-Shirt (Red) $15.99.

**Sorting confirmed (AC3) — read live from the DOM:**
- `lohi` → 7.99, 9.99, 15.99, 15.99, 29.99, 49.99 — `active-option` = "Price (low to high)" ✅
- `hilo` → 49.99, 29.99, 15.99, 15.99, 9.99, 7.99 — `active-option` = "Price (high to low)" ✅
- `za`  → Test.allTheThings(), Onesie, Fleece Jacket, Bolt T-Shirt, Bike Light, Backpack — `active-option` = "Name (Z to A)" ✅
- `az`  → alphabetical (default) ✅

**Add/Remove confirmed (AC4):** Adding the Backpack set the badge to `1` and the button to `Remove`; the state persisted after switching sort to `za`; removing it reverted the button to `Add to cart` and the `shopping-cart-badge` element was **absent from the DOM** (not empty text) at 0 items.

**Links confirmed (AC5):** Clicking the Backpack name link (`item-4-title-link`) navigated to `/inventory-item.html?id=4`, detail page showed "Sauce Labs Backpack" / "$29.99" with a `back-to-products` button.

### Observations
- Product internal ids are **fixed and independent of sort position**: Backpack=4, Bike Light=0, Bolt T-Shirt=1, Test.allTheThings() T-Shirt (Red)=3, Onesie=2, Fleece Jacket=5.
- Name/image link anchors have `href="#"`; navigation is JS-driven, so URL must be asserted after the click, not from `href`.
- The two $15.99 T-shirts tie; price sorts assert the numeric sequence and tolerate either relative order between the pair.
- The inventory page logs benign console errors (SauceDemo's third-party analytics/404 noise). **Not a functional defect** — no impact on any acceptance criterion. Noted as an observation only.

---

## 3. Automated Test Results (Steps 4 & 5)

### Test suites (5 files, 16 tests) in `apps/saucedemo/tests/product-catalog/`

| File | AC | Tests |
|---|---|---|
| `product-listing.spec.ts` | AC1 | 2 |
| `default-sort.spec.ts` | AC2 | 1 |
| `sorting.spec.ts` | AC3 | 5 |
| `add-remove.spec.ts` | AC4 | 4 |
| `product-details.spec.ts` | AC5 | 4 |

Each spec uses an inline `beforeEach` that repeats the seed login (goto `/`, fill credentials, click login, expect `/inventory.html`) — the seed file is not imported. Relative URLs only; web-first assertions; sorting verified by comparing live reads to a sorted copy.

### Initial run (chromium) — before healing
**11 passed / 5 failed.** The 5 failures were all **test-code/timing bugs**, not application defects.

### Healing activities (playwright-test-healer agent)

| # | Failing test(s) | Root cause | Fix |
|---|---|---|---|
| 1 | `product-details.spec.ts` × 3 | SPA renders the detail view one tick after the URL changes; reading `inventory-item-name` immediately caught the still-rendered 6-item list (strict-mode violation) | Wait for `back-to-products` (detail-only element) to be visible and assert the name locator `toHaveCount(1)` before reading it |
| 2 | `product-listing.spec.ts` (image test) | `img.naturalWidth` read as `0` before the image finished loading | `await expect(img).toHaveJSProperty('complete', true)` then `expect.poll(() => naturalWidth).toBeGreaterThan(0)` |
| 3 | `sorting.spec.ts` (Name Z→A) | Baseline names captured before the grid finished its initial render → empty array | `await expect(nameLocator).toHaveCount(6)` before capturing the baseline |

No assertions were weakened. Only files under `tests/product-catalog/` were edited (config/app.json/seed untouched).

### Final results — after healing

| Browser project | Tests | Pass | Fail | Skipped |
|---|---|---|---|---|
| saucedemo-chromium | 16 | 16 | 0 | 0 |
| saucedemo-firefox | 16 | 16 | 0 | 0 |
| saucedemo-webkit | 16 | 16 | 0 | 0 |
| saucedemo-mobile-chrome | 16 | 16 | 0 | 0 |
| **Total** | **64** | **64** | **0** | **0** |

Cross-browser run: `npx playwright test apps/saucedemo/tests/product-catalog/` → **64 passed (41.6s)**. Firefox passed without the intermittent `NS_ERROR_NET_TIMEOUT` noted in app agentNotes (no re-run needed this time).

---

## 4. Defects Log

**No defects found.** All acceptance criteria behaved as specified in manual and automated testing. The only issues encountered were in the generated test code (timing/locator races), which were healed in Step 5 and are documented in §3; they do not represent application defects.

Console-error noise on the inventory page (third-party analytics) is a pre-existing, non-functional observation, not a defect against this story.

---

## 5. Test Coverage Analysis

| Acceptance criterion | Manual | Automated | Coverage |
|---|---|---|---|
| AC1 Product Listing (6 products, full info) | ✅ | ✅ (2 tests) | Full |
| AC2 Default Sort (Name A→Z, alphabetical) | ✅ | ✅ (1 test) | Full |
| AC3 Sorting Options (az/za/lohi/hilo + active-option) | ✅ | ✅ (5 tests) | Full |
| AC4 Add/Remove (button toggle, badge, survives re-sort) | ✅ | ✅ (4 tests) | Full |
| AC5 Links to Product Details (name & image) | ✅ | ✅ (4 tests) | Full |

**Business rules covered:** all products always listed (AC1), sorting changes order only not contents (AC3 compares sorted copies), add/remove state matches the cart and persists across re-sort (AC4) and reflects between list and detail page (AC5 detail-add test).

**Gaps / recommendations:**
- Only the `standard_user` is exercised. Other SauceDemo personas (`problem_user`, `performance_glitch_user`, `visual_user`) could surface image/sort/timing anomalies and are candidates for a future hardening story.
- Full cart/checkout flow is out of scope here (covered by SCRUM-101 checkout story).
- Price-sort tie handling is intentionally tolerant; acceptable per AC3.

---

## 6. Summary and Recommendations

**Quality assessment:** The Product Catalog and Sorting feature is **stable and fully conformant** to SCRUM-103. All 5 acceptance criteria pass in both manual exploratory testing and automated execution across all four browser projects (64/64 green).

**Risk areas:** Low. The main technical nuance is the SPA's render-after-navigation timing (handled with web-first waits) and the fixed-but-non-positional product ids (encoded explicitly in the tests).

**Next steps:**
1. Merge the delivered test suite into the target repo (Step 7 PR).
2. Consider extending coverage to alternate user personas.
3. Keep the Firefox parallel-load `NS_ERROR_NET_TIMEOUT` caveat in mind for CI; re-run the Firefox project before healing if it recurs.

---

## Unattended decisions
- None required. The story file resolved uniquely, all ACs passed, and no "stop and ask" conditions were hit. All 5 initial test failures were deterministic test-code races and were auto-healed.
