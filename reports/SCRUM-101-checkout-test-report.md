# SCRUM-101 — Checkout E2E Test Execution Report

| | |
|---|---|
| **User story** | SCRUM-101 — E-commerce Checkout Process |
| **Application under test** | SauceDemo — https://www.saucedemo.com |
| **Test account** | `standard_user` / `secret_sauce` |
| **Test framework** | Playwright (TypeScript) `@playwright/test` ^1.63 |
| **Browser projects** | Chromium, Firefox, WebKit (Safari), Mobile Chrome (Pixel 7) |
| **Date executed** | 2026-10-03 |
| **Prepared by** | Automated QA agent workflow (plan → explore → generate → heal → report) |

---

## 1. Executive Summary

| Metric | Count |
|---|---|
| Acceptance criteria in scope | 5 (AC1–AC5) |
| Test scenarios planned | 22 |
| Manual (exploratory) scenarios executed | 7 key paths (all ACs) |
| Automated test cases | 22 |
| Automated executions (22 × 4 browsers) | 88 |
| **Automated pass rate** | **88 / 88 (100%)** |
| Tests healed | 1 |
| Blocked / not executed | 0 |
| **Overall status** | ✅ **PASS** |

All five acceptance criteria are fully covered by passing automated tests across all four configured browser projects. One generated test required healing (locator scoping / navigation wait) and passes after the fix. No application defects were found; two intentional validation-gap observations are documented below.

---

## 2. Manual (Exploratory) Test Results

Exploratory testing was performed by driving a real browser (Chromium) through the Playwright MCP tools, starting from the logged-in seed state (`tests/seed.spec.ts`).

| # | Scenario | AC | Result | Evidence |
|---|---|---|---|---|
| E1 | Add Backpack ($29.99) + Bike Light ($9.99); cart badge → 2 | AC1 | ✅ PASS | — |
| E2 | Cart page lists both items (qty 1, description, price); Continue Shopping + Checkout present; no total shown on cart page | AC1 | ✅ PASS | `evidence/01-cart-review.png` |
| E3 | Checkout → `/checkout-step-one.html`; Continue with all fields empty → **"Error: First Name is required"**, URL unchanged | AC2, AC5 | ✅ PASS | `evidence/02-info-validation-error.png` |
| E4 | Fill Jane / Smith / 94107 → `/checkout-step-two.html` | AC2 | ✅ PASS | — |
| E5 | Overview: both items, Payment **SauceCard #31337**, Shipping **Free Pony Express Delivery!**, Item total **$39.98**, Tax **$3.20**, Total **$43.18** | AC3 | ✅ PASS | `evidence/03-order-overview.png` |
| E6 | Finish → `/checkout-complete.html`, **"Thank you for your order!"**, dispatch text, Pony Express image, Back Home | AC4 | ✅ PASS | `evidence/04-order-complete.png` |
| E7 | Cart badge cleared after order completion | AC4, business rule 4 | ✅ PASS | `evidence/04-order-complete.png` |

### Observations from exploration
- **Totals math confirmed:** Tax = 8% of item total ($39.98 × 0.08 = $3.198 → displayed $3.20); Total = item total + tax.
- **Validation is sequential/top-to-bottom:** only one error shown at a time (First Name → Last Name → Postal Code).
- **Empty cart:** the `shopping-cart-badge` element is *absent* entirely (header reads "Cart, empty") — assertions check absence, not empty text.
- **Headings:** "Your Cart", "Checkout: Your Information", "Checkout: Overview" are exposed via a stable `[data-test="title"]` node (the order-complete header is a real `<h2>`).
- **Third-party console errors** from `events.backtrace.io` (analytics, `ERR_CONNECTION_RESET` / `401`) appear on every page. These are **not** application defects and are explicitly not asserted against.

---

## 3. Automated Test Results

Scripts: `tests/saucedemo-checkout/` — 9 spec files, 22 test cases. Each file logs in via a `beforeEach` replicating the seed, uses relative URLs (baseURL in `playwright.config.ts`), stable `data-test` locators, and web-first assertions (no fixed timeouts).

### 3.1 Test suite composition

| Spec file | Scenarios | Tests |
|---|---|---|
| `cart-review.spec.ts` | 1.1–1.4 (AC1) | 4 |
| `checkout-info.spec.ts` | 2.1 (AC2 happy path) | 1 |
| `checkout-info-validation.spec.ts` | 2.2–2.7 (AC2/AC5) | 6 |
| `checkout-info-edgecases.spec.ts` | 2.8–2.9 (edge cases) | 2 |
| `order-overview.spec.ts` | 3.1–3.3 (AC3) | 3 |
| `order-completion.spec.ts` | 4.1–4.2 (AC4) | 2 |
| `e2e-happy-path.spec.ts` | 5.1 (end-to-end) | 1 |
| `navigation-cancel.spec.ts` | 5.2–5.3 (cancel flows) | 2 |
| `ui-validation.spec.ts` | 6.1 (UI elements) | 1 |
| **Total** | | **22** |

### 3.2 Initial run (Chromium)

`npx playwright test tests/saucedemo-checkout/ --project=chromium`

- **Result: 21 passed, 1 failed.**
- Failure: `cart-review.spec.ts` → *"Continue Shopping returns to products page and preserves cart contents"*.

### 3.3 Healing activity

| Item | Detail |
|---|---|
| Failing test | Scenario 1.2 — Continue Shopping preserves cart |
| Root cause | Assertion used the unscoped locator `[data-test="inventory-item-name"]` immediately after clicking the cart link, without first waiting for navigation to `/cart.html`. It matched all 6 inventory-grid items → Playwright strict-mode violation. |
| Fix (by `playwright-test-healer` agent) | Wait for the cart page to load (`toHaveURL(/cart\.html/)` + `[data-test="title"]` = "Your Cart") before asserting, and scope the item-name check to the single cart row via `[data-test="inventory-item"].filter({ hasText: 'Sauce Labs Backpack' })` and a row-count of 1. Test intent (return to inventory with badge "1") preserved. |
| Outcome | Test passes on Chromium; no other test or `playwright.config.ts` modified. |

### 3.4 Final run — all browsers

`npx playwright test tests/saucedemo-checkout/`

| Browser project | Tests | Passed | Failed |
|---|---|---|---|
| Chromium | 22 | 22 | 0 |
| Firefox | 22 | 22 | 0 |
| WebKit (Safari) | 22 | 22 | 0 |
| Mobile Chrome (Pixel 7) | 22 | 22 | 0 |
| **Total** | **88** | **88** | **0** |

✅ **100% pass rate across all four browser projects. No browser-specific failures.**

---

## 4. Defects Log

**No application defects were found.** One generated-test defect was found and healed (see §3.3); it was a test-script issue, not an application issue.

### Non-defect observations (documented behavior, not bugs)

| ID | Type | Severity | Title | Notes |
|---|---|---|---|---|
| OBS-1 | Validation gap | Low | Whitespace-only First Name accepted | A First Name of only spaces (`"   "`) passes validation and proceeds to Overview. Encoded as an explicit edge-case test documenting current behavior. Flag to product if trimming is expected. |
| OBS-2 | Edge behavior | Low | Checkout reachable with empty cart | The checkout flow can be completed with an empty cart; Overview shows "Item total: $0" / "Total: $0.00" and Finish is enabled. Documented via test 3.3. Confirm against business rule 3 ("cart cannot be empty when proceeding to checkout"). |
| OBS-3 | Environment | Info | Third-party analytics console errors | `events.backtrace.io` requests fail (`ERR_CONNECTION_RESET` / `401`) on every page. External analytics, not app functionality. Not asserted against. |

> Note on business rules: the user story lists "Cart cannot be empty when proceeding to checkout" (rule 3). The live application does **not** enforce this — OBS-2 captures the discrepancy for product triage.

---

## 5. Test Coverage Analysis

| Acceptance criterion | Covered by (automated) | Manual | Status |
|---|---|---|---|
| **AC1 — Cart Review** | `cart-review.spec.ts` (4) | E1, E2 | ✅ Full |
| **AC2 — Checkout Information Entry** | `checkout-info.spec.ts`, `checkout-info-validation.spec.ts` | E3, E4 | ✅ Full |
| **AC3 — Order Overview** | `order-overview.spec.ts` (3) | E5 | ✅ Full |
| **AC4 — Order Completion** | `order-completion.spec.ts` (2) | E6, E7 | ✅ Full |
| **AC5 — Error Handling** | `checkout-info-validation.spec.ts` (6), `checkout-info-edgecases.spec.ts` (2) | E3 | ✅ Full |
| Navigation (cancel/back/e2e) | `e2e-happy-path.spec.ts`, `navigation-cancel.spec.ts` | E6 | ✅ Covered |
| UI element validation | `ui-validation.spec.ts` | E2, E5 | ✅ Covered |

**Coverage: all 5 acceptance criteria fully covered** by both manual and automated testing, plus navigation and UI validation.

### Gaps / recommendations for additional testing
- **Other user types:** only `standard_user` was tested. Add `problem_user`, `performance_glitch_user`, and `locked_out_user` to surface known SauceDemo quirks.
- **Quantity handling:** SauceDemo fixes quantity at 1; if multi-quantity is ever added, extend total-calculation tests.
- **Business-rule enforcement:** add negative tests once OBS-1 (whitespace trimming) and OBS-2 (empty-cart checkout block) are clarified by product.
- **Visual/responsive:** Mobile Chrome passes functionally; consider visual-regression snapshots for the checkout layout.
- **Accessibility:** consider an axe-core pass on each checkout page.

---

## 6. Summary & Recommendations

**Overall quality assessment:** The checkout workflow is **functionally solid**. Every acceptance criterion passes across all four browser projects (88/88), including validation, navigation, and order completion. No application defects were identified.

**Risk areas:**
- Input validation is lenient (whitespace-only names accepted — OBS-1).
- The documented business rule that checkout requires a non-empty cart is not enforced by the app (OBS-2).

**Next steps:**
1. Triage OBS-1 and OBS-2 with product to confirm intended behavior; add enforcement tests if rules change.
2. Extend coverage to additional SauceDemo user personas.
3. Wire `tests/saucedemo-checkout/` into CI (the repo already contains `.github/workflows/playwright.yml`).
4. Deliver artifacts via pull request to the target repository (Step 7 of the workflow).

---

### Appendix — Environment
- `playwright.config.ts`: `baseURL=https://www.saucedemo.com`, `actionTimeout=10s`, `navigationTimeout=15s`, trace on first retry, HTML + list reporters.
- Node project `e2e-playwright-test-agent`, `@playwright/test ^1.63.0`.
- Evidence screenshots: `reports/evidence/01-cart-review.png`, `02-info-validation-error.png`, `03-order-overview.png`, `04-order-complete.png`.
