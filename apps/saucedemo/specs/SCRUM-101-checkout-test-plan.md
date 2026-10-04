# SCRUM-101 E-commerce Checkout Process Test Plan

## Application Overview

This test plan covers the end-to-end checkout flow of the SauceDemo (Swag Labs) application at https://www.saucedemo.com, corresponding to user story SCRUM-101 (E-commerce Checkout Process). All scenarios assume the tester begins already logged in as `standard_user` on `/inventory.html` (via the shared seed `apps/saucedemo/seed.spec.ts`, credentials `standard_user` / `secret_sauce`), with an empty cart unless a scenario states otherwise. Each item must be added to the cart within the test itself.

Element locators use the stable `data-test` attribute convention: `page.locator('[data-test="..."]')`. The side menu must be opened using `getByRole('button', { name: 'Open Menu' })` — never via a direct/JS click on `[data-test="open-menu"]`.

Key flow/URL map discovered during exploration:
- Products: `/inventory.html`
- Cart: `/cart.html`
- Checkout Step One (information): `/checkout-step-one.html`
- Checkout Step Two (overview): `/checkout-step-two.html`
- Checkout Complete: `/checkout-complete.html`

Key locators discovered:
- Header: `[data-test="open-menu"]` (do not click directly — use role-based "Open Menu" button), `[data-test="shopping-cart-link"]`, `[data-test="shopping-cart-badge"]` (only present when cart is non-empty; shows item count)
- Inventory page: `[data-test="inventory-item-name"]`, `[data-test="inventory-item-desc"]`, `[data-test="inventory-item-price"]`, `[data-test="add-to-cart-sauce-labs-backpack"]` (and similar `add-to-cart-<slug>` ids per product, e.g. `add-to-cart-sauce-labs-bike-light`, `add-to-cart-sauce-labs-bolt-t-shirt`, `add-to-cart-sauce-labs-fleece-jacket`, `add-to-cart-sauce-labs-onesie`, `add-to-cart-test.allthethings()-t-shirt-(red)`), corresponding `remove-<slug>` buttons once added
- Cart page: `[data-test="cart-list"]`, `[data-test="cart-quantity-label"]`, `[data-test="cart-desc-label"]`, `[data-test="inventory-item-name"]`, `[data-test="inventory-item-desc"]`, `[data-test="inventory-item-price"]`, `[data-test="item-quantity"]`, `[data-test="remove-<slug>"]`, `[data-test="continue-shopping"]`, `[data-test="checkout"]`. NOTE: the cart page does NOT display a subtotal/total value anywhere — totals first appear on checkout-step-two.
- Checkout Step One: `[data-test="firstName"]`, `[data-test="lastName"]`, `[data-test="postalCode"]`, `[data-test="cancel"]`, `[data-test="continue"]`, error alert `[data-test="error"]`, error dismiss `[data-test="error-button"]`
- Checkout Step Two: `[data-test="cart-list"]` (same item rows as cart, but without Remove buttons), `[data-test="payment-info-label"]`/`[data-test="payment-info-value"]` ("SauceCard #31337"), `[data-test="shipping-info-label"]`/`[data-test="shipping-info-value"]` ("Free Pony Express Delivery!"), `[data-test="total-info-label"]`, `[data-test="subtotal-label"]` ("Item total: $X.XX"), `[data-test="tax-label"]` ("Tax: $X.XX"), `[data-test="total-label"]` ("Total: $X.XX"), `[data-test="cancel"]`, `[data-test="finish"]`
- Checkout Complete: `[data-test="checkout-complete-container"]`, `[data-test="pony-express"]` (image), `[data-test="complete-header"]` ("Thank you for your order!"), `[data-test="complete-text"]` ("Your order has been dispatched, and will arrive just as fast as the pony can get there!"), `[data-test="back-to-products"]` ("Back Home" button), `[data-test="generate-pdf-order"]`

Exact validation error strings observed (data-test="error" alert, dismissible via data-test="error-button"):
- Empty First Name: "Error: First Name is required"
- Empty Last Name (first name filled): "Error: Last Name is required"
- Empty Postal Code (first/last filled): "Error: Postal Code is required"
- All fields empty: shows First Name error first (fields are validated in order: firstName, lastName, postalCode)

Important actual-behavior findings (deviations from the idealized acceptance criteria that testers should be aware of and that the test plan codifies as expected/actual behavior rather than assumed behavior):
1. The cart page (`/cart.html`) does not render any subtotal/total text; totals only appear on checkout-step-two. AC1's "sees total" expectation does not hold literally on the cart page in the live app — tests should assert item list + Continue Shopping/Checkout buttons only, and verify totals later on step two.
2. Cancel behaves differently depending on which checkout step it's clicked from: Cancel on checkout-step-one returns to `/cart.html`; Cancel on checkout-step-two returns to `/inventory.html` (products), not to the cart.
3. The Checkout button on the cart page is NOT disabled/hidden when the cart is empty — a user can click Checkout, fill valid info, and reach checkout-step-two showing "Item total: $0", "Tax: $0.00", "Total: $0.00", and successfully Finish. This contradicts the "cart cannot be empty" business rule as a hard block; tests should document actual behavior.
4. Required-field validation only checks for an empty string, not trimmed content — entering a single space (" ") into First Name is accepted as "non-empty" and the form proceeds past validation.
5. Tax is calculated at 8% of item total, rounded to 2 decimals (e.g. items totaling $39.98 produce Tax: $3.20, Total: $43.18).
6. Completing checkout clears the cart (badge disappears / shows "Cart, empty") and clicking "Back Home" returns to `/inventory.html`.

## Test Scenarios

### 1. AC1 - Cart Review

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 1.1. Cart displays single added item with name, description, price, quantity and action buttons

**File:** `apps/saucedemo/specs/checkout/ac1-cart-review.spec.ts`

**Steps:**
  1. Start on /inventory.html (seeded, logged in).
    - expect: Inventory list is visible with 6 products.
  2. Click [data-test="add-to-cart-sauce-labs-backpack"].
    - expect: Button changes to 'Remove'.
    - expect: Cart badge [data-test="shopping-cart-badge"] shows '1'.
  3. Click [data-test="shopping-cart-link"].
    - expect: Navigates to /cart.html.
    - expect: Page header shows 'Your Cart'.
  4. Inspect the cart row for Sauce Labs Backpack.
    - expect: [data-test="inventory-item-name"] text is 'Sauce Labs Backpack'.
    - expect: [data-test="inventory-item-desc"] text matches the product description from inventory.
    - expect: [data-test="inventory-item-price"] text is '$29.99'.
    - expect: [data-test="item-quantity"] text is '1'.
  5. Inspect page-level controls.
    - expect: [data-test="continue-shopping"] button is visible.
    - expect: [data-test="checkout"] button is visible.
    - expect: No subtotal/total element is rendered on this page (confirmed actual app behavior).

#### 1.2. Cart displays multiple items each with correct name, description, price, quantity

**File:** `apps/saucedemo/specs/checkout/ac1-cart-review.spec.ts`

**Steps:**
  1. From /inventory.html, click [data-test="add-to-cart-sauce-labs-backpack"] then [data-test="add-to-cart-sauce-labs-bike-light"].
    - expect: Cart badge shows '2'.
  2. Click [data-test="shopping-cart-link"] to open /cart.html.
    - expect: Two cart item rows are rendered.
  3. Verify row 1 (Sauce Labs Backpack): name, desc, price '$29.99', qty '1'. Verify row 2 (Sauce Labs Bike Light): name, desc, price '$9.99', qty '1'.
    - expect: All fields match the product catalog values exactly.
    - expect: Items appear in the order they were added (or per app's deterministic ordering).
  4. Confirm [data-test="continue-shopping"] and [data-test="checkout"] are both present and enabled.
    - expect: Both buttons clickable.

#### 1.3. Continue Shopping from cart returns to products page preserving cart contents

**File:** `apps/saucedemo/specs/checkout/ac1-cart-review.spec.ts`

**Steps:**
  1. Add Sauce Labs Backpack to cart, navigate to /cart.html via [data-test="shopping-cart-link"].
    - expect: Cart shows 1 item.
  2. Click [data-test="continue-shopping"].
    - expect: URL returns to /inventory.html.
  3. Click [data-test="shopping-cart-link"] again.
    - expect: Cart still shows the Sauce Labs Backpack with quantity 1 (cart state preserved across navigation).

#### 1.4. Removing an item from the cart page updates the list and badge

**File:** `apps/saucedemo/specs/checkout/ac1-cart-review.spec.ts`

**Steps:**
  1. Add Sauce Labs Backpack and Sauce Labs Bike Light to cart; open /cart.html.
    - expect: Two rows visible, badge shows '2'.
  2. Click [data-test="remove-sauce-labs-backpack"].
    - expect: Backpack row disappears from the list.
    - expect: Badge updates to '1' (or disappears to 'Cart, empty' aria if it was the last item).
  3. Remove the remaining item [data-test="remove-sauce-labs-bike-light"].
    - expect: Cart list is empty.
    - expect: Cart badge element [data-test="shopping-cart-badge"] is no longer rendered; cart button aria-label is 'Cart, empty'.

### 2. AC2 - Checkout Information Entry & Validation

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 2.1. Clicking Checkout from cart navigates to checkout-step-one with empty mandatory fields

**File:** `apps/saucedemo/specs/checkout/ac2-checkout-information.spec.ts`

**Steps:**
  1. Add an item to cart and go to /cart.html.
    - expect: Cart has 1 item.
  2. Click [data-test="checkout"].
    - expect: URL is /checkout-step-one.html.
    - expect: Header text is 'Checkout: Your Information'.
  3. Inspect the form.
    - expect: [data-test="firstName"] textbox is visible and empty.
    - expect: [data-test="lastName"] textbox is visible and empty.
    - expect: [data-test="postalCode"] textbox is visible and empty.
    - expect: [data-test="cancel"] and [data-test="continue"] buttons are visible.

#### 2.2. Empty First Name shows required error and blocks progress

**File:** `apps/saucedemo/specs/checkout/ac2-checkout-information.spec.ts`

**Steps:**
  1. Add item to cart, navigate to /checkout-step-one.html via cart > Checkout.
    - expect: On checkout-step-one.
  2. Leave [data-test="firstName"] empty. Fill [data-test="lastName"]='Doe' and [data-test="postalCode"]='12345'.
    - expect: Fields populated as entered.
  3. Click [data-test="continue"].
    - expect: URL remains /checkout-step-one.html (no navigation).
    - expect: Error alert [data-test="error"] is visible with exact text 'Error: First Name is required'.
    - expect: [data-test="error-button"] dismiss (x) control is visible within the alert.

#### 2.3. Empty Last Name shows required error and blocks progress

**File:** `apps/saucedemo/specs/checkout/ac2-checkout-information.spec.ts`

**Steps:**
  1. Add item to cart, navigate to /checkout-step-one.html.
    - expect: On checkout-step-one.
  2. Fill [data-test="firstName"]='John'. Leave [data-test="lastName"] empty. Fill [data-test="postalCode"]='12345'.
    - expect: Fields populated as entered.
  3. Click [data-test="continue"].
    - expect: URL remains /checkout-step-one.html.
    - expect: Error alert [data-test="error"] text is exactly 'Error: Last Name is required'.

#### 2.4. Empty Postal/Zip Code shows required error and blocks progress

**File:** `apps/saucedemo/specs/checkout/ac2-checkout-information.spec.ts`

**Steps:**
  1. Add item to cart, navigate to /checkout-step-one.html.
    - expect: On checkout-step-one.
  2. Fill [data-test="firstName"]='John' and [data-test="lastName"]='Doe'. Leave [data-test="postalCode"] empty.
    - expect: Fields populated as entered.
  3. Click [data-test="continue"].
    - expect: URL remains /checkout-step-one.html.
    - expect: Error alert [data-test="error"] text is exactly 'Error: Postal Code is required'.

#### 2.5. All fields empty shows First Name required error (validation order)

**File:** `apps/saucedemo/specs/checkout/ac2-checkout-information.spec.ts`

**Steps:**
  1. Add item to cart, navigate to /checkout-step-one.html. Leave all three fields empty.
    - expect: Form is blank.
  2. Click [data-test="continue"] immediately.
    - expect: Error alert text is exactly 'Error: First Name is required' (confirms validation checks firstName first).

#### 2.6. Dismissing the error alert clears the message without losing already-entered data

**File:** `apps/saucedemo/specs/checkout/ac2-checkout-information.spec.ts`

**Steps:**
  1. Add item to cart, navigate to /checkout-step-one.html. Click [data-test="continue"] with empty form.
    - expect: Error alert 'Error: First Name is required' is visible.
  2. Click [data-test="error-button"] (dismiss / x icon inside the alert).
    - expect: Error alert [data-test="error"] is no longer present in the DOM/visible.
    - expect: Form fields remain as previously entered (empty in this case).

#### 2.7. Re-submitting after fixing one field at a time progresses through each validation error sequentially

**File:** `apps/saucedemo/specs/checkout/ac2-checkout-information.spec.ts`

**Steps:**
  1. Add item to cart, go to /checkout-step-one.html. Click Continue with all empty.
    - expect: Error: 'Error: First Name is required'.
  2. Fill firstName='John'. Click Continue again.
    - expect: Error updates to 'Error: Last Name is required'.
  3. Fill lastName='Doe'. Click Continue again.
    - expect: Error updates to 'Error: Postal Code is required'.
  4. Fill postalCode='12345'. Click Continue again.
    - expect: Navigation succeeds to /checkout-step-two.html; no error shown.

#### 2.8. Whitespace-only value in a required field bypasses required validation (edge case / actual-behavior)

**File:** `apps/saucedemo/specs/checkout/ac2-checkout-information.spec.ts`

**Steps:**
  1. Add item to cart, go to /checkout-step-one.html.
    - expect: On checkout-step-one.
  2. Fill [data-test="firstName"] with a single space ' '. Fill [data-test="lastName"]='Tester' and [data-test="postalCode"]='11111'.
    - expect: Fields contain entered values.
  3. Click [data-test="continue"].
    - expect: Navigation succeeds to /checkout-step-two.html (documents that required-check only tests for empty string, not trimmed content — not a hard block in the live app).

#### 2.9. Special characters and unicode in Name/Postal fields are accepted

**File:** `apps/saucedemo/specs/checkout/ac2-checkout-information.spec.ts`

**Steps:**
  1. Add item to cart, go to /checkout-step-one.html.
    - expect: On checkout-step-one.
  2. Fill [data-test="firstName"]="Jean-Luc O'Brien 测试", [data-test="lastName"]="Müller-Schmidt #2", [data-test="postalCode"]="A1B 2C3".
    - expect: Fields accept and display the entered special characters.
  3. Click [data-test="continue"].
    - expect: No validation error is shown.
    - expect: Navigation succeeds to /checkout-step-two.html.

#### 2.10. Very long input values in Name/Postal fields are accepted without truncation error

**File:** `apps/saucedemo/specs/checkout/ac2-checkout-information.spec.ts`

**Steps:**
  1. Add item to cart, go to /checkout-step-one.html.
    - expect: On checkout-step-one.
  2. Fill firstName and lastName with 100-character strings (e.g. repeated 'A'), postalCode with a 20-character numeric string.
    - expect: Fields accept the long values (verify no character limit truncation causes mismatch, or note the max length if the app enforces one).
  3. Click [data-test="continue"].
    - expect: No validation error related to length; navigation proceeds to /checkout-step-two.html.

#### 2.11. Cancel on checkout-step-one returns user to the cart page

**File:** `apps/saucedemo/specs/checkout/ac2-checkout-information.spec.ts`

**Steps:**
  1. Add item to cart, go to /checkout-step-one.html.
    - expect: On checkout-step-one.
  2. Optionally partially fill firstName only. Click [data-test="cancel"].
    - expect: URL returns to /cart.html.
    - expect: The previously added cart item is still present (cart state unaffected by cancel).

### 3. AC3 - Order Overview (checkout-step-two)

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 3.1. Valid info submission navigates to Overview and displays correct item summary

**File:** `apps/saucedemo/specs/checkout/ac3-order-overview.spec.ts`

**Steps:**
  1. Add Sauce Labs Backpack ($29.99) and Sauce Labs Bike Light ($9.99) to cart. Go to /cart.html then click [data-test="checkout"].
    - expect: On /checkout-step-one.html.
  2. Fill firstName='Jane', lastName='Smith', postalCode='90210'. Click [data-test="continue"].
    - expect: URL is /checkout-step-two.html.
    - expect: Header text is 'Checkout: Overview'.
  3. Inspect item rows in [data-test="cart-list"].
    - expect: Two rows shown: Sauce Labs Backpack (qty 1, $29.99) and Sauce Labs Bike Light (qty 1, $9.99), each with name and description matching the product catalog.
    - expect: No 'Remove' buttons are present on this summary (read-only view).

#### 3.2. Overview page displays Payment and Shipping information

**File:** `apps/saucedemo/specs/checkout/ac3-order-overview.spec.ts`

**Steps:**
  1. Add one item to cart and complete checkout-step-one with valid data to reach /checkout-step-two.html.
    - expect: On Overview page.
  2. Inspect [data-test="payment-info-label"] and [data-test="payment-info-value"].
    - expect: Label text 'Payment Information:'.
    - expect: Value text 'SauceCard #31337'.
  3. Inspect [data-test="shipping-info-label"] and [data-test="shipping-info-value"].
    - expect: Label text 'Shipping Information:'.
    - expect: Value text 'Free Pony Express Delivery!'.

#### 3.3. Overview page computes subtotal, tax (8%), and total correctly for multiple items

**File:** `apps/saucedemo/specs/checkout/ac3-order-overview.spec.ts`

**Steps:**
  1. Add Sauce Labs Backpack ($29.99) and Sauce Labs Bike Light ($9.99) to cart (expected item total $39.98). Complete checkout-step-one with valid data.
    - expect: On /checkout-step-two.html.
  2. Read [data-test="subtotal-label"].
    - expect: Text is exactly 'Item total: $39.98'.
  3. Read [data-test="tax-label"].
    - expect: Text is exactly 'Tax: $3.20' (8% of $39.98 = $3.1984, rounded to $3.20).
  4. Read [data-test="total-label"].
    - expect: Text is exactly 'Total: $43.18' (= item total + tax).

#### 3.4. Overview page shows Cancel and Finish buttons

**File:** `apps/saucedemo/specs/checkout/ac3-order-overview.spec.ts`

**Steps:**
  1. Complete checkout-step-one with valid data for a cart with 1 item.
    - expect: On /checkout-step-two.html.
  2. Verify presence of [data-test="cancel"] and [data-test="finish"] buttons.
    - expect: Both buttons are visible and enabled.

#### 3.5. Cancel on checkout-step-two returns to the Products page (not the cart)

**File:** `apps/saucedemo/specs/checkout/ac3-order-overview.spec.ts`

**Steps:**
  1. Add item to cart and complete checkout-step-one with valid data to reach /checkout-step-two.html.
    - expect: On Overview page.
  2. Click [data-test="cancel"].
    - expect: URL is /inventory.html (Products page) — this differs from step-one's Cancel which returns to /cart.html.
    - expect: Cart badge still reflects the previously added item (order was not completed, so cart is retained).

#### 3.6. Single-item order overview math sanity check

**File:** `apps/saucedemo/specs/checkout/ac3-order-overview.spec.ts`

**Steps:**
  1. Add only Sauce Labs Onesie ($7.99) to cart, complete checkout-step-one with valid data.
    - expect: On /checkout-step-two.html.
  2. Read subtotal/tax/total labels.
    - expect: Item total: $7.99.
    - expect: Tax equals 8% of $7.99 rounded to 2 decimals ($0.64).
    - expect: Total equals $8.63 (sum of the two).

### 4. AC4 - Order Completion

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 4.1. End-to-end happy path: single item checkout completes successfully

**File:** `apps/saucedemo/specs/checkout/ac4-order-completion.spec.ts`

**Steps:**
  1. From /inventory.html, click [data-test="add-to-cart-sauce-labs-backpack"].
    - expect: Cart badge shows '1'.
  2. Click [data-test="shopping-cart-link"], then [data-test="checkout"].
    - expect: On /checkout-step-one.html.
  3. Fill firstName='John', lastName='Doe', postalCode='12345'. Click [data-test="continue"].
    - expect: On /checkout-step-two.html showing 1 item, Item total: $29.99, Tax: $2.40, Total: $32.39.
  4. Click [data-test="finish"].
    - expect: URL is /checkout-complete.html.
    - expect: Header 'Checkout: Complete!' is shown.
  5. Inspect completion content.
    - expect: [data-test="complete-header"] text is 'Thank you for your order!'.
    - expect: [data-test="complete-text"] text is 'Your order has been dispatched, and will arrive just as fast as the pony can get there!'.
    - expect: [data-test="pony-express"] image is visible.
    - expect: [data-test="back-to-products"] button ('Back Home') is visible.

#### 4.2. End-to-end happy path: multiple items checkout completes successfully

**File:** `apps/saucedemo/specs/checkout/ac4-order-completion.spec.ts`

**Steps:**
  1. Add Sauce Labs Backpack, Sauce Labs Bike Light, and Sauce Labs Bolt T-Shirt to cart.
    - expect: Cart badge shows '3'.
  2. Go to /cart.html, verify 3 rows, click [data-test="checkout"].
    - expect: On /checkout-step-one.html.
  3. Fill valid firstName/lastName/postalCode, click [data-test="continue"].
    - expect: On /checkout-step-two.html with 3 item rows and correct Item total/Tax/Total ($55.97 / $4.48 / $60.45).
  4. Click [data-test="finish"].
    - expect: On /checkout-complete.html with success message.

#### 4.3. Back Home button navigates to Products page after completion

**File:** `apps/saucedemo/specs/checkout/ac4-order-completion.spec.ts`

**Steps:**
  1. Complete a full checkout for 1 item to reach /checkout-complete.html.
    - expect: Completion page visible.
  2. Click [data-test="back-to-products"].
    - expect: URL is /inventory.html.
    - expect: Products grid is visible again.

#### 4.4. Cart is cleared after order completion

**File:** `apps/saucedemo/specs/checkout/ac4-order-completion.spec.ts`

**Steps:**
  1. Add 2 items to cart, complete checkout through Finish to reach /checkout-complete.html.
    - expect: [data-test="shopping-cart-badge"] is not present on the completion page; cart button aria-label is 'Cart, empty'.
  2. Click [data-test="back-to-products"] to return to /inventory.html.
    - expect: All Add to cart buttons read 'Add to cart' again (no items remain 'Remove').
    - expect: Cart badge remains absent / 'Cart, empty'.
  3. Navigate directly to [data-test="shopping-cart-link"] > /cart.html.
    - expect: Cart list is empty; no item rows rendered.

#### 4.5. Generate PDF order control is present on completion page (non-blocking UI check)

**File:** `apps/saucedemo/specs/checkout/ac4-order-completion.spec.ts`

**Steps:**
  1. Complete a checkout to reach /checkout-complete.html.
    - expect: Completion page visible.
  2. Verify [data-test="generate-pdf-order"] button is present alongside [data-test="back-to-products"].
    - expect: Button is visible (click behavior out of scope for this story; presence only).

### 5. AC5 / Business Rules - Edge Cases, Navigation, and Error Handling

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 5.1. Checkout button remains accessible with an empty cart and overview shows $0 totals (actual-behavior edge case)

**File:** `apps/saucedemo/specs/checkout/ac5-edge-cases.spec.ts`

**Steps:**
  1. Navigate to /cart.html directly with no items added (fresh seeded state).
    - expect: Cart list is empty.
    - expect: [data-test="checkout"] button is still visible and enabled despite empty cart.
  2. Click [data-test="checkout"].
    - expect: Navigates to /checkout-step-one.html without any error about an empty cart.
  3. Fill firstName='Empty', lastName='Cart', postalCode='00000'. Click [data-test="continue"].
    - expect: Navigates to /checkout-step-two.html.
    - expect: [data-test="subtotal-label"] text is 'Item total: $0'.
    - expect: [data-test="tax-label"] text is 'Tax: $0.00'.
    - expect: [data-test="total-label"] text is 'Total: $0.00'.
    - expect: No item rows are rendered in the summary.
  4. Click [data-test="finish"].
    - expect: Navigates to /checkout-complete.html and shows the standard success message even though the order contained zero items (documents actual app behavior vs. the 'cart cannot be empty' business rule).

#### 5.2. Navigating directly to checkout-step-one URL while logged in and cart has items

**File:** `apps/saucedemo/specs/checkout/ac5-edge-cases.spec.ts`

**Steps:**
  1. Add an item to cart via inventory page.
    - expect: Cart badge shows '1'.
  2. Use browser navigation to go directly to https://www.saucedemo.com/checkout-step-one.html (bypassing the cart page click).
    - expect: Page loads normally showing the empty information form (app does not block direct URL navigation for a logged-in user).

#### 5.3. Full navigation loop: Products -> Cart -> Checkout Step One -> Cancel -> Cart -> Checkout -> Step Two -> Cancel -> Products

**File:** `apps/saucedemo/specs/checkout/ac5-edge-cases.spec.ts`

**Steps:**
  1. Add item to cart from /inventory.html.
    - expect: Cart badge '1'.
  2. Go to /cart.html via [data-test="shopping-cart-link"].
    - expect: Cart shows the item.
  3. Click [data-test="checkout"] to reach /checkout-step-one.html, then click [data-test="cancel"].
    - expect: Returns to /cart.html; item still present.
  4. Click [data-test="checkout"] again, fill valid info, click [data-test="continue"] to reach /checkout-step-two.html, then click [data-test="cancel"].
    - expect: Returns to /inventory.html; item still present in cart (badge '1').

#### 5.4. Item quantity cannot be changed from cart or overview (no quantity input) — UI validation

**File:** `apps/saucedemo/specs/checkout/ac5-edge-cases.spec.ts`

**Steps:**
  1. Add one item to cart and go to /cart.html.
    - expect: [data-test="item-quantity"] shows '1' as plain text, not an editable input/select.
  2. Proceed through checkout to /checkout-step-two.html.
    - expect: Quantity on the overview page is also plain text '1', confirming quantity is fixed at 1 per add-to-cart action and not adjustable in this flow.

#### 5.5. Attempting checkout while adding the same item twice only reflects one 'Remove' state (no duplicate line, qty stays 1)

**File:** `apps/saucedemo/specs/checkout/ac5-edge-cases.spec.ts`

**Steps:**
  1. Click [data-test="add-to-cart-sauce-labs-backpack"] once; observe button becomes 'Remove' (data-test becomes remove-sauce-labs-backpack) so a second click is not possible via the same button.
    - expect: Cart badge shows '1', confirming no duplicate-add path exists through the UI for the same product.

#### 5.6. Error message disappears automatically once valid data is submitted (no stale error on success)

**File:** `apps/saucedemo/specs/checkout/ac5-edge-cases.spec.ts`

**Steps:**
  1. Add item to cart, go to /checkout-step-one.html, click [data-test="continue"] with empty form.
    - expect: Error 'Error: First Name is required' visible.
  2. Fill all three fields with valid data (firstName='Valid', lastName='User', postalCode='54321') and click [data-test="continue"].
    - expect: Navigation succeeds to /checkout-step-two.html.
    - expect: No error alert is present anywhere on the new page.

#### 5.7. Returning to checkout-step-one after Cancel from step-two retains or clears previously entered personal info (data retention check)

**File:** `apps/saucedemo/specs/checkout/ac5-edge-cases.spec.ts`

**Steps:**
  1. Add item to cart, go to /checkout-step-one.html, fill firstName='Retain', lastName='Test', postalCode='99999', click Continue to reach /checkout-step-two.html.
    - expect: On Overview page.
  2. Click [data-test="cancel"] to return to /inventory.html, then navigate back to /cart.html > [data-test="checkout"] to reach /checkout-step-one.html again.
    - expect: Form fields [data-test="firstName"], [data-test="lastName"], [data-test="postalCode"] are empty (fresh form), confirming the app does not persist previously entered info across a cancelled session.
