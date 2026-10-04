# SCRUM-104 Product Details Page Test Plan

## Application Overview

SauceDemo (https://www.saucedemo.com) is a demo e-commerce app used for test automation practice. This plan covers SCRUM-104 "Product Details Page": the inventory-item.html detail view reachable from the catalog or by direct URL (?id=<n>), covering content parity with the catalog, add/remove-from-cart behavior and badge sync, back-navigation, direct-link access control, and the unknown-product (id=999) edge case.

All tests assume a fresh browser context. Login is performed with standard_user / secret_sauce unless a test explicitly requires being logged out. The seed file (apps/saucedemo/seed.spec.ts) logs in and lands on /inventory.html; tests that need a logged-out state should log out via the side menu (Open Menu button, then "Logout") or clear cookies/storage, not skip the seed.

Discovered product id <-> name <-> price mapping (ids are NOT in catalog display order; verified by opening each detail page and visiting https://www.saucedemo.com/inventory-item.html?id=<n> directly):
| id | Name | Price | Description (verified identical on catalog and detail page) |
|----|------|-------|---------------|
| 0 | Sauce Labs Bike Light | $9.99 | A red light isn't the desired state in testing but it sure helps when riding your bike at night. Water-resistant with 3 lighting modes, 1 AAA battery included. |
| 1 | Sauce Labs Bolt T-Shirt | $15.99 | Get your testing superhero on with the Sauce Labs bolt T-shirt. From American Apparel, 100% ringspun combed cotton, heather gray with red bolt. |
| 2 | Sauce Labs Onesie | $7.99 | Rib snap infant onesie for the junior automation engineer in development. Reinforced 3-snap bottom closure, two-needle hemmed sleeved and bottom won't unravel. |
| 3 | Test.allTheThings() T-Shirt (Red) | $15.99 | This classic Sauce Labs t-shirt is perfect to wear when cozying up to your keyboard to automate a few tests. Super-soft and comfy ringspun combed cotton. |
| 4 | Sauce Labs Backpack | $29.99 | carry.allTheThings() with the sleek, streamlined Sly Pack that melds uncompromising style with unequaled laptop and tablet protection. |
| 5 | Sauce Labs Fleece Jacket | $49.99 | It's not every day that you come across a midweight quarter-zip fleece jacket capable of handling everything from a relaxing day outdoors to a busy day at the office. |

Stable locators (data-test unless noted):
- Catalog item name/title link: `[data-test="item-<id>-title-link"]` (id is the product's real id, e.g. `item-4-title-link` for Backpack)
- Catalog price: `.inventory_item_price` / `[data-test="inventory-item-price"]`
- Detail page product name: `[data-test="inventory-item-name"]`
- Detail page description: `[data-test="inventory-item-desc"]`
- Detail page price: `[data-test="inventory-item-price"]`
- Detail page product image: `.inventory_details_img` (alt attribute equals the product name, e.g. alt="Sauce Labs Backpack"; for id=999 alt="ITEM NOT FOUND")
- Add to cart (detail page, NO slug): `[data-test="add-to-cart"]`
- Remove (detail page, NO slug): `[data-test="remove"]`
- Back to products button: `[data-test="back-to-products"]`
- Cart badge: `[data-test="shopping-cart-badge"]` (absent entirely when cart is empty, i.e. "Cart, empty" aria-label with no badge text)
- Open side menu: use role button `getByRole('button', { name: 'Open Menu' })` (NOT `[data-test="open-menu"]`)
- Logout link in menu: `[data-test="logout-sidebar-link"]`
- Reset App State link in menu: `[data-test="reset-sidebar-link"]`
- Login error banner: `[data-test="error"]`

Observations recorded during exploration (include in plan as noted-behavior / potential-bug callouts, not as hard pass/fail assertions unless stated):
1. Opening /inventory-item.html?id=999 while logged in renders a page with: name "ITEM NOT FOUND", a joke description ("We're sorry, but your call could not be completed as dialled...This is a recording. 4 T 1."), price "$√-1", an image with alt="ITEM NOT FOUND", and a fully functional "Add to cart" button. "Back to products" works normally from this page.
2. BUG/anomaly: clicking "Add to cart" on the id=999 "ITEM NOT FOUND" page DOES increment the cart badge (e.g. to "1") and DOES change the button to "Remove" (so add/remove toggling works even for the non-existent item) — but when the cart page (/cart.html) is then opened, no cart line item is rendered (the QTY/Description table is empty) even though the badge still shows 1 item. This is a data-integrity inconsistency worth flagging to the dev team.
3. When logged out and navigating directly to /inventory-item.html?id=<any>, the app always redirects to "/" (login page) and shows the alert `[data-test="error"]` with exact text: "Epic sadface: You can only access '/inventory-item.html' when you are logged in." This happens regardless of the id value (confirmed with id=4 and id=2), i.e. the auth guard fires before any id lookup.
4. The side menu overlay content (All Items / Dynamic Catalog / About / Logout / Reset App State) is present but visually hidden (aria-hidden) until "Open Menu" is clicked, confirming the documented locator approach of using the accessible role name rather than a data-test id for opening it.

## Test Scenarios

### 1. AC1 - Detail Content Parity

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 1.1. Detail page shows correct name, description, price, and image for every one of the 6 products

**File:** `apps/saucedemo/tests/product-details/ac1-detail-content-parity.spec.ts`

**Steps:**
  1. Start on /inventory.html (post seed login). Capture each catalog product's name, description, and price via [data-test="inventory-item-name"]/[data-test="inventory-item-desc"]/[data-test="inventory-item-price"] within each .inventory_item, along with its id by reading the href/id of its [data-test$="title-link"] element.
    - expect: 6 inventory items are visible
    - expect: Each item's title-link id attribute is of the form item_<n>_title_link, giving ids 0,1,2,3,4,5 mapped to Bike Light, Bolt T-Shirt, Onesie, Test.allTheThings() T-Shirt (Red), Backpack, Fleece Jacket respectively
  2. For each discovered id (0 through 5), navigate directly to /inventory-item.html?id=<id>
    - expect: Page loads with URL /inventory-item.html?id=<id>
    - expect: [data-test="inventory-item-name"] text matches the catalog name captured for that id
    - expect: [data-test="inventory-item-desc"] text matches the catalog description captured for that id
    - expect: [data-test="inventory-item-price"] text matches the catalog price captured for that id (e.g. id=4 -> "Sauce Labs Backpack" / $29.99 / carry.allTheThings()... )
  3. On each detail page, locate the product image via .inventory_details_img
    - expect: An <img> with class inventory_details_img is present and visible
    - expect: Its alt attribute equals the product name shown on that page (e.g. alt="Sauce Labs Fleece Jacket" for id=5)
    - expect: Its src attribute is non-empty
  4. Repeat the above checks by clicking each product's title/image link from the catalog instead of typing the URL (for at least 2 of the 6 products, e.g. Bike Light id=0 and Backpack id=4)
    - expect: Clicking the product name or image navigates to /inventory-item.html?id=<correct id> and shows the same name/description/price/image as verified via direct URL

#### 1.2. Detail page layout always includes back-to-products control and header cart icon regardless of product

**File:** `apps/saucedemo/tests/product-details/ac1-detail-layout.spec.ts`

**Steps:**
  1. Navigate to /inventory-item.html?id=2 (Onesie)
    - expect: [data-test="back-to-products"] button is visible in the header
    - expect: The cart icon button is visible in the header (aria-label "Cart, empty" when cart is empty)
  2. Navigate to /inventory-item.html?id=5 (Fleece Jacket)
    - expect: Same header elements ([data-test="back-to-products"], cart icon) are present
    - expect: Product-specific content (name/desc/price/image) updates to Fleece Jacket values

### 2. AC2 - Add/Remove From Cart on Detail Page

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 2.1. Add to cart from detail page updates button label and cart badge

**File:** `apps/saucedemo/tests/product-details/ac2-add-to-cart.spec.ts`

**Steps:**
  1. Navigate to /inventory-item.html?id=4 (Backpack). Confirm starting state.
    - expect: [data-test="add-to-cart"] button is visible showing text "Add to cart"
    - expect: Cart icon shows aria-label "Cart, empty" and [data-test="shopping-cart-badge"] is not present
  2. Click [data-test="add-to-cart"]
    - expect: Button is replaced by [data-test="remove"] showing text "Remove"
    - expect: Cart icon aria-label becomes "Cart, 1 items"
    - expect: [data-test="shopping-cart-badge"] becomes visible with text "1"

#### 2.2. Remove from detail page reverts button label and decrements cart badge

**File:** `apps/saucedemo/tests/product-details/ac2-remove-from-cart.spec.ts`

**Steps:**
  1. Navigate to /inventory-item.html?id=4 and click [data-test="add-to-cart"] to add the Backpack to the cart
    - expect: Button becomes [data-test="remove"] ("Remove"), badge shows "1"
  2. Click [data-test="remove"]
    - expect: Button reverts to [data-test="add-to-cart"] showing "Add to cart"
    - expect: Cart badge disappears entirely ([data-test="shopping-cart-badge"] not present) and cart icon aria-label returns to "Cart, empty"

#### 2.3. Adding multiple different products increments the badge cumulatively across detail-page visits

**File:** `apps/saucedemo/tests/product-details/ac2-multiple-add.spec.ts`

**Steps:**
  1. Navigate to /inventory-item.html?id=0 (Bike Light) and click [data-test="add-to-cart"]
    - expect: Badge shows "1"
    - expect: Button on this page now shows "Remove"
  2. Navigate to /inventory-item.html?id=1 (Bolt T-Shirt) and click [data-test="add-to-cart"]
    - expect: Badge shows "2" (cumulative, not reset by navigation)
    - expect: Button on this page shows "Remove"
  3. Navigate to /inventory-item.html?id=5 (Fleece Jacket)
    - expect: Button on this page still shows "Add to cart" (it was never added) confirming per-product state is independent, badge remains "2"

#### 2.4. A product already in the cart opens its detail page showing Remove (state persists on reopen)

**File:** `apps/saucedemo/tests/product-details/ac2-reopen-shows-remove.spec.ts`

**Steps:**
  1. From the catalog (/inventory.html), click "Add to cart" for Sauce Labs Backpack (catalog's add-to-cart-sauce-labs-backpack control)
    - expect: Catalog badge shows "1" and the Backpack's catalog button becomes "Remove"
  2. Navigate directly to /inventory-item.html?id=4 (Backpack's id)
    - expect: Page loads showing Backpack details
    - expect: [data-test="remove"] button is shown (NOT "Add to cart"), proving cart state carried over from the catalog action
  3. Click [data-test="remove"] on the detail page
    - expect: Button reverts to "Add to cart"
    - expect: Badge disappears
  4. Navigate back to /inventory.html
    - expect: Backpack's catalog tile button shows "Add to cart" again, confirming the removal on the detail page also reflects back in the catalog

### 3. AC3 - Back to Products Navigation and State Sync

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 3.1. Back to products returns to the catalog URL

**File:** `apps/saucedemo/tests/product-details/ac3-back-to-products.spec.ts`

**Steps:**
  1. Navigate to /inventory-item.html?id=3 (Test.allTheThings() T-Shirt Red)
    - expect: Detail page is shown for id=3
  2. Click [data-test="back-to-products"]
    - expect: URL becomes /inventory.html
    - expect: The full 6-item catalog grid is visible again with default sort "Name (A to Z)"

#### 3.2. Cart changes made on the detail page are reflected on the catalog after Back to products

**File:** `apps/saucedemo/tests/product-details/ac3-state-sync-after-back.spec.ts`

**Steps:**
  1. Navigate to /inventory-item.html?id=4 (Backpack) and click [data-test="add-to-cart"]
    - expect: Button becomes "Remove"; badge shows "1"
  2. Click [data-test="back-to-products"]
    - expect: Returns to /inventory.html
    - expect: Cart badge still shows "1"
    - expect: The Sauce Labs Backpack tile's button shows "Remove" (matches the detail-page action)
  3. On the catalog, click "Remove" on the Backpack tile, then navigate back to /inventory-item.html?id=4
    - expect: Detail page shows "Add to cart" button, confirming two-way sync between catalog and detail page

### 4. AC4 - Direct Link Access Control

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 4.1. Direct navigation to a valid product id while logged in shows that product

**File:** `apps/saucedemo/tests/product-details/ac4-direct-link-logged-in.spec.ts`

**Steps:**
  1. While logged in (post seed), navigate directly to /inventory-item.html?id=5 without clicking through the catalog
    - expect: Page loads at /inventory-item.html?id=5
    - expect: [data-test="inventory-item-name"] shows "Sauce Labs Fleece Jacket", price shows "$49.99", matching the mapping table
  2. Repeat for id=1 (Bolt T-Shirt)
    - expect: Detail page shows "Sauce Labs Bolt T-Shirt", "$15.99"

#### 4.2. Direct navigation to a product id while logged out redirects to login with protected-page error

**File:** `apps/saucedemo/tests/product-details/ac4-direct-link-logged-out.spec.ts`

**Steps:**
  1. Starting from the logged-in seed state, open the side menu via getByRole('button', { name: 'Open Menu' }) and click [data-test="logout-sidebar-link"] to log out (alternative: clear cookies and localStorage/sessionStorage)
    - expect: User is redirected to the login page at "/"
  2. Navigate directly to /inventory-item.html?id=4
    - expect: App redirects to "/" (login page) instead of showing the detail page
    - expect: [data-test="error"] alert is visible with exact text: "Epic sadface: You can only access '/inventory-item.html' when you are logged in."
  3. Repeat navigating directly to /inventory-item.html?id=2 while still logged out
    - expect: Same redirect and identical error text occur regardless of which id was requested, confirming the auth guard fires before any product lookup
  4. Log back in with standard_user / secret_sauce
    - expect: User lands on /inventory.html with an empty cart (clean state) for subsequent tests

### 5. AC5 - Unknown Product Handling

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 5.1. Unknown product id shows ITEM NOT FOUND content

**File:** `apps/saucedemo/tests/product-details/ac5-item-not-found.spec.ts`

**Steps:**
  1. While logged in, navigate directly to /inventory-item.html?id=999
    - expect: Page loads without crashing/erroring at the network level
    - expect: [data-test="inventory-item-name"] shows "ITEM NOT FOUND"
    - expect: [data-test="inventory-item-desc"] shows the placeholder joke text beginning "We're sorry, but your call could not be completed as dialled..."
    - expect: [data-test="inventory-item-price"] shows the placeholder value "$√-1"
    - expect: The product image (.inventory_details_img) has alt="ITEM NOT FOUND"

#### 5.2. Back to products works from the ITEM NOT FOUND page

**File:** `apps/saucedemo/tests/product-details/ac5-not-found-back-nav.spec.ts`

**Steps:**
  1. Navigate to /inventory-item.html?id=999
    - expect: ITEM NOT FOUND content is shown as above
  2. Click [data-test="back-to-products"]
    - expect: Navigation succeeds and URL becomes /inventory.html with the normal 6-item catalog visible (no leftover broken state)

#### 5.3. OBSERVATION: Add to cart on the ITEM NOT FOUND page toggles state but produces an inconsistent cart entry (record as bug/anomaly, do not hard-fail CI on this without team confirmation)

**File:** `apps/saucedemo/tests/product-details/ac5-not-found-add-to-cart-anomaly.spec.ts`

**Steps:**
  1. Navigate to /inventory-item.html?id=999 and click [data-test="add-to-cart"]
    - expect: Button becomes [data-test="remove"] showing "Remove"
    - expect: Cart badge increments to "1" even though no real product exists for id=999
  2. Navigate to /cart.html
    - expect: Badge still shows "1" item
    - expect: ANOMALY: the cart item list (QTY / Description table) renders empty — no visible row for the id=999 item, despite the badge count being 1. Record this discrepancy as a finding; if the team decides this is expected/acceptable behavior, downgrade this assertion to a soft check or remove it
  3. Open the side menu (getByRole('button', { name: 'Open Menu' })) and click [data-test="reset-sidebar-link"] to clean up state
    - expect: Cart badge is cleared
    - expect: Returning to /inventory.html shows all products with "Add to cart" buttons and no badge

#### 5.4. Boundary id values are handled gracefully (negative, zero-padded, non-numeric)

**File:** `apps/saucedemo/tests/product-details/ac5-boundary-ids.spec.ts`

**Steps:**
  1. Navigate to /inventory-item.html?id=-1
    - expect: Page does not crash; shows either a valid product or ITEM NOT FOUND-style content consistently with the id=999 behavior observed in exploration
  2. Navigate to /inventory-item.html?id=abc (non-numeric)
    - expect: Page does not crash; shows ITEM NOT FOUND-style content or another clearly defined fallback; [data-test="back-to-products"] remains clickable and returns to /inventory.html
  3. Navigate to /inventory-item.html (no id query param at all)
    - expect: Page does not crash; document the actual rendered behavior (e.g. defaults to ITEM NOT FOUND or to the first product) as a finding if it differs from the id=999 case
