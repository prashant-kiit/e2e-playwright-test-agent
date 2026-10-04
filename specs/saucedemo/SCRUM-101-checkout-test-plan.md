# SauceDemo Checkout E2E Test Plan (SCRUM-101)

## Application Overview

## Application Under Test
SauceDemo (https://www.saucedemo.com) - a demo e-commerce site used for test automation practice.

## Scope
End-to-end checkout workflow covering: Cart Review, Checkout Information entry, Order Overview, Order Completion, and related error handling / edge cases, per user story SCRUM-101.

## Starting State / Assumptions
- All scenarios assume a fresh browser session that has already authenticated as `standard_user` / `secret_sauce` and landed on `/inventory.html` (see seed file `tests/saucedemo/seed.spec.ts`).
- `baseURL` is configured in `playwright.config.ts`; all navigation in generated tests should use relative paths (e.g. `/cart.html`, `/checkout-step-one.html`).
- Unless a scenario states otherwise, the cart is assumed empty at the start of each scenario (use "Reset App State" from the burger menu, or remove items, to guarantee isolation between tests).

## Key Stable Locators Discovered (data-test attributes)

### Inventory page (`/inventory.html`)
- `[data-test="add-to-cart-<item-slug>"]` / `[data-test="remove-<item-slug>"]` - e.g. `add-to-cart-sauce-labs-backpack`
- `[data-test="shopping-cart-link"]` - cart icon/link in header
- `[data-test="shopping-cart-badge"]` - item count badge (absent entirely when cart is empty)
- `[data-test="inventory-item-name"]`, `[data-test="inventory-item-desc"]`, `[data-test="inventory-item-price"]`

### Cart page (`/cart.html`)
- `[data-test="cart-list"]`, `[data-test="cart-quantity-label"]`, `[data-test="cart-desc-label"]`
- `[data-test="inventory-item"]` (row), `[data-test="item-quantity"]`
- `[data-test="inventory-item-name"]`, `[data-test="inventory-item-desc"]`, `[data-test="inventory-item-price"]`
- `[data-test="remove-<item-slug>"]`
- `[data-test="continue-shopping"]`, `[data-test="checkout"]`
- NOTE: the cart page does NOT render a subtotal/total - totals only appear on the Overview page.

### Checkout Step One - Information (`/checkout-step-one.html`)
- `[data-test="firstName"]`, `[data-test="lastName"]`, `[data-test="postalCode"]`
- `[data-test="cancel"]`, `[data-test="continue"]`
- `[data-test="error"]` (error banner text), `[data-test="error-button"]` (dismiss "X")
- Confirmed error copy: "Error: First Name is required", "Error: Last Name is required", "Error: Postal Code is required". Validation runs top-to-bottom; only the first missing field's error is shown at a time.
- Known gap: a whitespace-only value (e.g. "   ") in First Name is NOT treated as empty and passes validation.

### Checkout Step Two - Overview (`/checkout-step-two.html`)
- `[data-test="checkout-summary-container"]`
- `[data-test="cart-list"]`, `[data-test="item-quantity"]`, `[data-test="inventory-item-name"]`, `[data-test="inventory-item-desc"]`, `[data-test="inventory-item-price"]`
- `[data-test="payment-info-label"]`, `[data-test="payment-info-value"]` (e.g. "SauceCard #31337")
- `[data-test="shipping-info-label"]`, `[data-test="shipping-info-value"]` (e.g. "Free Pony Express Delivery!")
- `[data-test="total-info-label"]`, `[data-test="subtotal-label"]` ("Item total: $X"), `[data-test="tax-label"]` ("Tax: $X"), `[data-test="total-label"]` ("Total: $X")
- `[data-test="cancel"]`, `[data-test="finish"]`

### Checkout Complete (`/checkout-complete.html`)
- `[data-test="checkout-complete-container"]`, `[data-test="pony-express"]` (image)
- `[data-test="complete-header"]` ("Thank you for your order!")
- `[data-test="complete-text"]` ("Your order has been dispatched, and will arrive just as fast as the pony can get there!")
- `[data-test="back-to-products"]`, `[data-test="generate-pdf-order"]`

## Confirmed Navigation / Business Rules
- Cancel on Step One -> returns to `/cart.html`, cart contents preserved.
- Cancel on Step Two (Overview) -> returns to `/inventory.html`, cart contents preserved (badge count unchanged).
- Finish on Overview -> navigates to `/checkout-complete.html` AND clears the cart (badge disappears).
- "Back Home" on the complete page -> returns to `/inventory.html` with an empty cart.
- The Checkout button and checkout flow remain accessible even when the cart is empty; Overview then shows "Item total: $0" / "Total: $0.00".

## Test Scenarios

### 1. AC1 - Cart Review

**Seed:** `tests/saucedemo/seed.spec.ts`

#### 1.1. Cart displays correct item details, quantities, and supports navigation options

**File:** `tests/checkout/cart-review.spec.ts`

**Steps:**
  1. Starting on /inventory.html (logged in), add 'Sauce Labs Backpack' ($29.99) and 'Sauce Labs Bike Light' ($9.99) to the cart using their Add to cart buttons.
    - expect: The shopping cart badge shows '2'
  2. Click the shopping cart link/icon in the header.
    - expect: Page navigates to /cart.html
    - expect: Page title/header reads 'Your Cart'
  3. Inspect the cart list rows.
    - expect: Sauce Labs Backpack row shows quantity '1', its description text, and price '$29.99'
    - expect: Sauce Labs Bike Light row shows quantity '1', its description text, and price '$9.99'
    - expect: Both 'Continue Shopping' and 'Checkout' buttons are visible and enabled

#### 1.2. Continue Shopping returns to products page and preserves cart contents

**File:** `tests/checkout/cart-review.spec.ts`

**Steps:**
  1. Add 'Sauce Labs Backpack' to the cart from /inventory.html, then open the cart page.
    - expect: Cart badge shows '1' and the backpack appears in the cart list
  2. Click 'Continue Shopping' (data-test=continue-shopping).
    - expect: Page navigates back to /inventory.html
    - expect: Cart badge still shows '1', confirming the cart item was not lost

#### 1.3. Removing an item from the cart updates the list and badge count

**File:** `tests/checkout/cart-review.spec.ts`

**Steps:**
  1. Add 'Sauce Labs Backpack' and 'Sauce Labs Bike Light' to the cart, then open /cart.html.
    - expect: Both items are listed and badge shows '2'
  2. Click 'Remove' (data-test=remove-sauce-labs-backpack) on the Backpack row.
    - expect: The Backpack row disappears from the cart list
    - expect: Only the Bike Light remains
    - expect: Cart badge updates to '1'

#### 1.4. Checkout button navigates to the Information step, and remains accessible with an empty cart

**File:** `tests/checkout/cart-review.spec.ts`

**Steps:**
  1. With the cart empty, navigate to /cart.html.
    - expect: No item rows are rendered
    - expect: The 'Checkout' button is still visible and enabled
  2. Click 'Checkout' (data-test=checkout).
    - expect: Page navigates to /checkout-step-one.html showing the 'Checkout: Your Information' form

### 2. AC2 & AC5 - Checkout Information Entry and Validation

**Seed:** `tests/saucedemo/seed.spec.ts`

#### 2.1. Happy path: valid First Name, Last Name, and Zip proceed to Overview

**File:** `tests/checkout/checkout-info.spec.ts`

**Steps:**
  1. Add any product to the cart and navigate to /checkout-step-one.html.
    - expect: Form shows empty First Name, Last Name, and Zip/Postal Code fields plus Cancel/Continue buttons
  2. Fill First Name = 'John', Last Name = 'Doe', Zip/Postal Code = '12345' (data-test=firstName/lastName/postalCode).
    - expect: Fields reflect the entered values, no error banner is shown
  3. Click 'Continue' (data-test=continue).
    - expect: Page navigates to /checkout-step-two.html ('Checkout: Overview')
    - expect: No validation error is displayed

#### 2.2. Negative: empty First Name blocks submission with a field-specific error

**File:** `tests/checkout/checkout-info-validation.spec.ts`

**Steps:**
  1. Navigate to /checkout-step-one.html (with an item in cart). Leave First Name empty, fill Last Name = 'Doe', Zip = '12345'.
    - expect: Form fields are populated as entered
  2. Click 'Continue'.
    - expect: URL remains /checkout-step-one.html (submission blocked)
    - expect: An error banner (data-test=error) reads 'Error: First Name is required'

#### 2.3. Negative: empty Last Name blocks submission with a field-specific error

**File:** `tests/checkout/checkout-info-validation.spec.ts`

**Steps:**
  1. Navigate to /checkout-step-one.html (with an item in cart). Fill First Name = 'John', leave Last Name empty, fill Zip = '12345'.
    - expect: Form fields are populated as entered
  2. Click 'Continue'.
    - expect: URL remains /checkout-step-one.html
    - expect: Error banner reads 'Error: Last Name is required'

#### 2.4. Negative: empty Zip/Postal Code blocks submission with a field-specific error

**File:** `tests/checkout/checkout-info-validation.spec.ts`

**Steps:**
  1. Navigate to /checkout-step-one.html (with an item in cart). Fill First Name = 'John', Last Name = 'Doe', leave Zip/Postal Code empty.
    - expect: Form fields are populated as entered
  2. Click 'Continue'.
    - expect: URL remains /checkout-step-one.html
    - expect: Error banner reads 'Error: Postal Code is required'

#### 2.5. Negative: all fields empty surfaces the first missing field's error

**File:** `tests/checkout/checkout-info-validation.spec.ts`

**Steps:**
  1. Navigate to /checkout-step-one.html (with an item in cart) and immediately click 'Continue' without entering any data.
    - expect: URL remains /checkout-step-one.html
    - expect: Error banner reads 'Error: First Name is required' (the first field in form order), not a generic or multi-field message

#### 2.6. Error banner can be dismissed via the close (X) control

**File:** `tests/checkout/checkout-info-validation.spec.ts`

**Steps:**
  1. On /checkout-step-one.html, click 'Continue' with all fields empty to trigger the error banner.
    - expect: Error banner 'Error: First Name is required' is visible with a dismiss button (data-test=error-button)
  2. Click the dismiss (X) button on the error banner.
    - expect: The error banner is no longer visible
    - expect: Form fields remain editable and empty
  3. Fill all three fields with valid data and click Continue again.
    - expect: Page proceeds to /checkout-step-two.html successfully

#### 2.7. Sequential correction: fixing one invalid field at a time reveals the next required field error

**File:** `tests/checkout/checkout-info-validation.spec.ts`

**Steps:**
  1. On /checkout-step-one.html with all fields empty, click Continue.
    - expect: Error: 'Error: First Name is required' is shown
  2. Fill First Name = 'John' only, click Continue again.
    - expect: Error updates to 'Error: Last Name is required'
  3. Fill Last Name = 'Doe', leave Zip empty, click Continue again.
    - expect: Error updates to 'Error: Postal Code is required'
  4. Fill Zip = '12345' and click Continue.
    - expect: Page proceeds successfully to /checkout-step-two.html

#### 2.8. Edge case: whitespace-only First Name is accepted (documents current validation gap)

**File:** `tests/checkout/checkout-info-edgecases.spec.ts`

**Steps:**
  1. On /checkout-step-one.html, fill First Name with only spaces ('   '), Last Name = 'Doe', Zip = '12345'.
    - expect: Fields show the entered values
  2. Click 'Continue'.
    - expect: Current behavior: the app treats the whitespace value as non-empty and navigates to /checkout-step-two.html (no 'required' error is raised). Flag this as a known validation gap if stricter trimming is expected by the business.

#### 2.9. Edge case: special characters and long values are accepted in text fields

**File:** `tests/checkout/checkout-info-edgecases.spec.ts`

**Steps:**
  1. On /checkout-step-one.html, fill First Name = "O'Brien-Test123", Last Name = a 100-character string, Zip = 'AB-123 456'.
    - expect: Fields accept and display the entered values without truncation errors
  2. Click 'Continue'.
    - expect: Page proceeds to /checkout-step-two.html (no client-side format validation blocks special characters or long strings)

### 3. AC3 - Order Overview

**Seed:** `tests/saucedemo/seed.spec.ts`

#### 3.1. Overview page shows item summary, payment/shipping info, and correct subtotal/tax/total

**File:** `tests/checkout/order-overview.spec.ts`

**Steps:**
  1. Add 'Sauce Labs Backpack' ($29.99) to the cart, go to /checkout-step-one.html, fill valid First Name/Last Name/Zip, and click Continue.
    - expect: Page navigates to /checkout-step-two.html ('Checkout: Overview')
  2. Inspect the item summary section.
    - expect: Row shows quantity '1', 'Sauce Labs Backpack' name, its description, and price '$29.99'
  3. Inspect the Payment Information and Shipping Information sections.
    - expect: Payment Information shows a value like 'SauceCard #31337'
    - expect: Shipping Information shows 'Free Pony Express Delivery!'
  4. Inspect the Price Total section.
    - expect: 'Item total: $29.99' is shown
    - expect: 'Tax: $2.40' is shown
    - expect: 'Total: $32.39' is shown (item total + tax)
    - expect: Both 'Cancel' and 'Finish' buttons are visible and enabled

#### 3.2. Overview totals correctly aggregate multiple cart items

**File:** `tests/checkout/order-overview.spec.ts`

**Steps:**
  1. Add 'Sauce Labs Backpack' ($29.99) and 'Sauce Labs Bike Light' ($9.99) to the cart and proceed through checkout info with valid data to reach /checkout-step-two.html.
    - expect: Both items are listed in the overview with correct individual prices
  2. Inspect the Item total line.
    - expect: Item total equals $39.98 (sum of both item prices)
  3. Inspect the Tax and Total lines.
    - expect: Tax is calculated as a percentage of the item total
    - expect: Total equals Item total + Tax, displayed to 2 decimal places

#### 3.3. Edge case: Overview with an empty cart shows zeroed totals

**File:** `tests/checkout/order-overview.spec.ts`

**Steps:**
  1. With the cart empty, navigate directly to /checkout-step-one.html, fill valid First Name/Last Name/Zip, and click Continue.
    - expect: Page proceeds to /checkout-step-two.html despite no items in cart
  2. Inspect the item list and totals.
    - expect: No item rows are rendered
    - expect: 'Item total: $0' is shown
    - expect: 'Total: $0.00' is shown
    - expect: 'Finish' button is still enabled

### 4. AC4 - Order Completion

**Seed:** `tests/saucedemo/seed.spec.ts`

#### 4.1. Clicking Finish completes the order, shows the confirmation message, and clears the cart

**File:** `tests/checkout/order-completion.spec.ts`

**Steps:**
  1. Add 'Sauce Labs Backpack' to the cart and complete the checkout info form with valid data to reach /checkout-step-two.html.
    - expect: Overview page is displayed with the backpack listed
  2. Click 'Finish' (data-test=finish).
    - expect: Page navigates to /checkout-complete.html
    - expect: Header (data-test=complete-header) reads 'Thank you for your order!'
    - expect: Body text (data-test=complete-text) reads 'Your order has been dispatched, and will arrive just as fast as the pony can get there!'
    - expect: A pony express image (data-test=pony-express) is visible
    - expect: 'Back Home' button (data-test=back-to-products) is visible
  3. Check the header cart icon.
    - expect: The shopping cart badge is no longer present (cart has been cleared)

#### 4.2. Back Home button returns to the products page with an empty cart

**File:** `tests/checkout/order-completion.spec.ts`

**Steps:**
  1. Complete a full checkout (add item, fill info, finish) to reach /checkout-complete.html.
    - expect: Confirmation page is shown
  2. Click 'Back Home' (data-test=back-to-products).
    - expect: Page navigates to /inventory.html
    - expect: Cart badge is absent, confirming the cart remains empty after order completion

### 5. Navigation Flow - Cancel, Back, and End-to-End Happy Path

**Seed:** `tests/saucedemo/seed.spec.ts`

#### 5.1. End-to-end happy path: Inventory to Cart to Info to Overview to Completion

**File:** `tests/checkout/e2e-happy-path.spec.ts`

**Steps:**
  1. From /inventory.html, add 'Sauce Labs Backpack' and 'Sauce Labs Bike Light' to the cart.
    - expect: Cart badge shows '2'
  2. Open the cart via the cart icon.
    - expect: Both items are listed on /cart.html with correct details
  3. Click 'Checkout'.
    - expect: Page navigates to /checkout-step-one.html
  4. Fill First Name = 'Jane', Last Name = 'Smith', Zip = '94107', then click 'Continue'.
    - expect: Page navigates to /checkout-step-two.html showing both items, payment/shipping info, and correct totals
  5. Click 'Finish'.
    - expect: Page navigates to /checkout-complete.html with the 'Thank you for your order!' confirmation and cleared cart
  6. Click 'Back Home'.
    - expect: Page returns to /inventory.html with an empty cart, ready for a new order

#### 5.2. Cancel on Checkout Information page returns to Cart and preserves items

**File:** `tests/checkout/navigation-cancel.spec.ts`

**Steps:**
  1. Add 'Sauce Labs Backpack' to the cart and navigate to /checkout-step-one.html.
    - expect: Checkout information form is displayed
  2. Optionally fill some fields, then click 'Cancel' (data-test=cancel).
    - expect: Page navigates back to /cart.html
    - expect: 'Sauce Labs Backpack' is still listed in the cart (no data loss)

#### 5.3. Cancel on Order Overview page returns to Products and preserves cart contents

**File:** `tests/checkout/navigation-cancel.spec.ts`

**Steps:**
  1. Add 'Sauce Labs Backpack' to the cart, complete the checkout info form with valid data, and reach /checkout-step-two.html.
    - expect: Overview page is displayed with the backpack listed
  2. Click 'Cancel' on the overview page.
    - expect: Page navigates to /inventory.html (not back to the info form)
    - expect: Cart badge still shows '1', confirming the order was not submitted and the cart item is preserved

### 6. UI Element Validation

**Seed:** `tests/saucedemo/seed.spec.ts`

#### 6.1. All expected UI elements are present and correctly labeled across the checkout flow

**File:** `tests/checkout/ui-validation.spec.ts`

**Steps:**
  1. On /cart.html (with at least one item), inspect the page structure.
    - expect: Column headers 'QTY' and 'Description' are visible
    - expect: 'Continue Shopping' and 'Checkout' buttons are present with correct, clickable state
  2. Navigate to /checkout-step-one.html.
    - expect: Page heading reads 'Checkout: Your Information'
    - expect: First Name, Last Name, and Zip/Postal Code inputs are present with correct placeholder text
    - expect: 'Cancel' and 'Continue' buttons are present and enabled
  3. Complete the form and proceed to /checkout-step-two.html.
    - expect: Page heading reads 'Checkout: Overview'
    - expect: Payment Information and Shipping Information section labels are present
    - expect: Price Total section shows item total, tax, and total labels
    - expect: 'Cancel' and 'Finish' buttons are present and enabled
  4. Click 'Finish' to reach /checkout-complete.html.
    - expect: Confirmation header, body text, pony express image, and 'Back Home' button are all present and visible
