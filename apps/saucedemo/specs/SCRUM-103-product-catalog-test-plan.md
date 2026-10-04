# SCRUM-103 — Product Catalog and Sorting Test Plan

## Application Overview

This test plan covers SCRUM-103 (Product Catalog and Sorting) for the SauceDemo (Swag Labs) application. All scenarios assume a fresh browser session that has completed the standard login flow (standard_user / secret_sauce) and landed on the Products page (https://www.saucedemo.com/inventory.html), as performed by the shared seed file apps/saucedemo/seed.spec.ts.

Confirmed live locators (verified via the saucedemo-chromium project):
- Page title: [data-test="title"] → "Products"
- Product grid container: [data-test="inventory-list"]
- Each product card: [data-test="inventory-item"]
- Product name: [data-test="inventory-item-name"]
- Product description: [data-test="inventory-item-desc"]
- Product price: [data-test="inventory-item-price"] (format "$NN.NN")
- Add to cart button: button[data-test="add-to-cart-<slug>"] (slug = lower-case name, spaces → "-", special chars kept, e.g. sauce-labs-backpack, test.allthethings()-t-shirt-(red))
- Remove button (after add): button[data-test="remove-<slug>"]
- Sort dropdown (a <select>): [data-test="product-sort-container"], options with value/text: az/"Name (A to Z)", za/"Name (Z to A)", lohi/"Price (low to high)", hilo/"Price (high to low)"
- Currently selected sort label: [data-test="active-option"] (text node next to the dropdown, e.g. "Name (A to Z)")
- Cart badge: [data-test="shopping-cart-badge"] (absent from DOM entirely when cart is empty; contains a number as text when >0)
- Cart icon button: button named "Open Menu" is separate; cart is the button with accessible name "Cart, N items" / "Cart, empty" near [data-test="shopping-cart-link"] in header — badge lives inside it
- Product name link (navigates to detail page): [data-test="item-<id>-title-link"]
- Product image link (navigates to detail page): [data-test="item-<id>-img-link"]
- Detail page URL pattern: https://www.saucedemo.com/inventory-item.html?id=<id>
- Detail page product name: [data-test="inventory-item-name"] (reused data-test, scoped to detail page body)
- Detail page back button: button[data-test="back-to-products"]
- Side menu open button: getByRole('button', { name: 'Open Menu' }) (per app quirk notes; do NOT use [data-test="open-menu"])

Verified live data (read directly from the DOM on 2026-10-04, saucedemo-chromium project):
| id | Name | Price | add-to-cart data-test |
|----|------|-------|------------------------|
| 4 | Sauce Labs Backpack | $29.99 | add-to-cart-sauce-labs-backpack |
| 0 | Sauce Labs Bike Light | $9.99 | add-to-cart-sauce-labs-bike-light |
| 1 | Sauce Labs Bolt T-Shirt | $15.99 | add-to-cart-sauce-labs-bolt-t-shirt |
| 5 | Sauce Labs Fleece Jacket | $49.99 | add-to-cart-sauce-labs-fleece-jacket |
| 2 | Sauce Labs Onesie | $7.99 | add-to-cart-sauce-labs-onesie |
| 3 | Test.allTheThings() T-Shirt (Red) | $15.99 | add-to-cart-test.allthethings()-t-shirt-(red) |

Important: product ids (used in item-<id>-title-link / item-<id>-img-link / inventory-item.html?id=<id>) do NOT correspond to the default alphabetical display order. Tests must map id→name dynamically by reading the item's own name text at click time, never by hard-coding an id-to-name assumption.

Confirmed behavior from live exploration:
- Default sort on fresh load is "Name (A to Z)" (az), matching AC2.
- Selecting "lohi" produced order: Onesie($7.99), Bike Light($9.99), Bolt T-Shirt($15.99), Test.allTheThings($15.99), Backpack($29.99), Fleece Jacket($49.99) — correctly sorted ascending by price with the two $15.99 items adjacent (either relative order acceptable).
- Clicking "Add to cart" on Onesie: button becomes "Remove" (data-test changes to remove-sauce-labs-onesie), badge appears with text "1".
- Changing sort order (az → za) while Onesie is in cart: Onesie button still reads "Remove" (state survives re-sort), confirming AC4's persistence requirement.
- Clicking "Remove": badge is removed entirely from the DOM (not just text "0"); button reverts to "Add to cart".
- Clicking a product's name link (item-4-title-link, Backpack) navigates to /inventory-item.html?id=4 and the detail page shows name "Sauce Labs Backpack", price "$29.99" — matching the clicked product.
- Clicking a product's image link (item-0-img-link, Bike Light) navigates to /inventory-item.html?id=0 — also correct.
- Detail page has its own "Add to cart" button and a "Back to products" button (data-test="back-to-products") that returns to /inventory.html.

## Test Scenarios

### 1. AC1 - Product Listing

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 1.1. Products page lists exactly 6 products with correct names and prices

**File:** `apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md`

**Steps:**
  1. Start from the Products page (post-seed login state).
    - expect: Page title [data-test="title"] shows 'Products'.
    - expect: URL is https://www.saucedemo.com/inventory.html
  2. Count the number of elements matching [data-test="inventory-item"] inside [data-test="inventory-list"].
    - expect: Exactly 6 inventory-item elements are present.
  3. Read the text of [data-test="inventory-item-name"] inside each of the 6 inventory-item elements and collect into a set.
    - expect: The set equals exactly: {'Sauce Labs Backpack', 'Sauce Labs Bike Light', 'Sauce Labs Bolt T-Shirt', 'Sauce Labs Fleece Jacket', 'Sauce Labs Onesie', 'Test.allTheThings() T-Shirt (Red)'} with no duplicates and no extras.
  4. For each inventory-item, read [data-test="inventory-item-price"] and build a name→price map.
    - expect: Sauce Labs Backpack = $29.99
    - expect: Sauce Labs Bike Light = $9.99
    - expect: Sauce Labs Bolt T-Shirt = $15.99
    - expect: Sauce Labs Fleece Jacket = $49.99
    - expect: Sauce Labs Onesie = $7.99
    - expect: Test.allTheThings() T-Shirt (Red) = $15.99

#### 1.2. Each product card renders image, name, description, price, and an Add to cart button

**File:** `apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md`

**Steps:**
  1. For each of the 6 [data-test="inventory-item"] cards, assert presence of a visible <img> element (the product image / image link).
    - expect: Each card has exactly one visible product image, locatable via [data-test="item-<id>-img-link"] containing an <img>.
  2. Within each card, assert [data-test="inventory-item-name"] is visible and non-empty.
    - expect: Name text is visible and matches one of the 6 expected product names.
  3. Within each card, assert [data-test="inventory-item-desc"] is visible and non-empty.
    - expect: Description text is visible and non-empty for all 6 products.
  4. Within each card, assert [data-test="inventory-item-price"] is visible and matches the pattern $NN.NN.
    - expect: Price is visible and formatted correctly for all 6 products.
  5. Within each card, assert a button matching button[data-test^="add-to-cart-"] is visible and enabled, with accessible name 'Add to cart'.
    - expect: All 6 cards show an enabled 'Add to cart' button prior to any interaction.

#### 1.3. Negative: no pagination or filtering controls exist, and product count/content is stable on reload

**File:** `apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md`

**Steps:**
  1. On the Products page, search the DOM for any pagination controls (e.g. 'Next', 'Page 2', numbered page links) or filter inputs besides the sort dropdown.
    - expect: No pagination or filter controls are found; [data-test="product-sort-container"] is the only listing-control element.
  2. Reload the page (navigate to https://www.saucedemo.com/inventory.html again).
    - expect: Exactly 6 inventory-item elements are still present with the same 6 names and prices as in the first scenario.
    - expect: Sort resets to default 'Name (A to Z)' on reload.

### 2. AC2 - Default Sort State

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 2.1. Sort dropdown defaults to Name (A to Z) and products are listed alphabetically on fresh load

**File:** `apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md`

**Steps:**
  1. On the freshly loaded Products page, read the selected value of [data-test="product-sort-container"].
    - expect: Selected option value is 'az' and its label is 'Name (A to Z)'.
  2. Read the text of [data-test="active-option"] next to the dropdown.
    - expect: Text reads 'Name (A to Z)'.
  3. Read the [data-test="inventory-item-name"] text of all 6 products in DOM order into array A.
    - expect: Array A captured, e.g. ['Sauce Labs Backpack','Sauce Labs Bike Light','Sauce Labs Bolt T-Shirt','Sauce Labs Fleece Jacket','Sauce Labs Onesie','Test.allTheThings() T-Shirt (Red)']
  4. Create array B = a copy of A sorted alphabetically (case-sensitive or locale 'en' compare, ascending) using the test framework's own sort, not hard-coded values.
    - expect: Array B computed independently from A.
  5. Assert A deep-equals B.
    - expect: A matches B exactly, confirming the default on-screen order is true alphabetical (A to Z) order.

### 3. AC3 - Sorting Options

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 3.1. Name (Z to A) sort reorders products in reverse alphabetical order and dropdown reflects selection

**File:** `apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md`

**Steps:**
  1. Select option with value 'za' on [data-test="product-sort-container"] (e.g. page.locator('[data-test="product-sort-container"]').selectOption('za')).
    - expect: Dropdown's selected option becomes 'Name (Z to A)'.
    - expect: [data-test="active-option"] text updates to 'Name (Z to A)'.
  2. Read [data-test="inventory-item-name"] text of all 6 products in DOM order into array A.
    - expect: Array A captured reflecting the new on-screen order.
  3. Create array B = a copy of A sorted alphabetically ascending, then reverse it to get descending order, computed independently (not hard-coded).
    - expect: Array B computed as the expected Z-to-A order.
  4. Assert A deep-equals B.
    - expect: On-screen order is exactly reverse-alphabetical.
  5. Assert the same 6 product names from AC1 are present in A (as a set), with none added or removed.
    - expect: Set of names unchanged; only order changed.

#### 3.2. Price (low to high) sort reorders products by ascending price; equal-priced items may appear in either relative order

**File:** `apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md`

**Steps:**
  1. Select option with value 'lohi' on [data-test="product-sort-container"].
    - expect: Dropdown's selected option becomes 'Price (low to high)'.
    - expect: [data-test="active-option"] text updates to 'Price (low to high)'.
  2. Read [data-test="inventory-item-price"] (parsed as a float, stripping '$') of all 6 products in DOM order into array P.
    - expect: Array P of 6 numeric prices captured, e.g. [7.99, 9.99, 15.99, 15.99, 29.99, 49.99].
  3. Create array Q = a copy of P sorted numerically ascending, computed independently.
    - expect: Q computed as the expected ascending price order.
  4. Assert P deep-equals Q.
    - expect: On-screen price order is non-decreasing from first to last card.
  5. Identify the two cards priced at $15.99 (Sauce Labs Bolt T-Shirt and Test.allTheThings() T-Shirt (Red)) and assert both appear consecutively somewhere in the list (in either relative order).
    - expect: Both $15.99 items are present and adjacent to each other in the sorted list; their specific left-right order is not asserted.

#### 3.3. Price (high to low) sort reorders products by descending price; equal-priced items may appear in either relative order

**File:** `apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md`

**Steps:**
  1. Select option with value 'hilo' on [data-test="product-sort-container"].
    - expect: Dropdown's selected option becomes 'Price (high to low)'.
    - expect: [data-test="active-option"] text updates to 'Price (high to low)'.
  2. Read [data-test="inventory-item-price"] (parsed as float) of all 6 products in DOM order into array P.
    - expect: Array P of 6 numeric prices captured, e.g. [49.99, 29.99, 15.99, 15.99, 9.99, 7.99].
  3. Create array Q = a copy of P sorted numerically descending, computed independently.
    - expect: Q computed as the expected descending price order.
  4. Assert P deep-equals Q.
    - expect: On-screen price order is non-increasing from first to last card.
  5. Assert the two $15.99 items are adjacent in the list regardless of their mutual order.
    - expect: Both T-shirts priced $15.99 sit next to each other.

#### 3.4. Switching back to Name (A to Z) from another sort restores alphabetical order

**File:** `apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md`

**Steps:**
  1. Starting from 'hilo' sort (price high to low) applied in a prior step, select option value 'az' on [data-test="product-sort-container"].
    - expect: Dropdown's selected option becomes 'Name (A to Z)'.
    - expect: [data-test="active-option"] text reads 'Name (A to Z)'.
  2. Read [data-test="inventory-item-name"] order into array A and compare against an independently alphabetically-sorted copy B.
    - expect: A deep-equals B, confirming correct re-application of default sort.

#### 3.5. Repeatedly cycling through all 4 sort options preserves the full set of 6 products each time (count/contents invariant)

**File:** `apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md`

**Steps:**
  1. In sequence, select 'az', then 'za', then 'lohi', then 'hilo', then 'az' again on [data-test="product-sort-container"], reading the full set of [data-test="inventory-item-name"] values after each selection.
    - expect: After every single sort change, exactly 6 inventory-item cards are present.
    - expect: After every single sort change, the set of 6 product names exactly equals the AC1 baseline set (no additions, removals, or duplicates) — only the order differs.

### 4. AC4 - Add and Remove from the List (Cart Badge Behavior)

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 4.1. Adding a single product changes its button to Remove and increments the cart badge to 1

**File:** `apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md`

**Steps:**
  1. On the Products page (default sort), assert [data-test="shopping-cart-badge"] is absent from the DOM (cart starts empty).
    - expect: No shopping-cart-badge element exists; cart icon shows no count.
  2. Click button[data-test="add-to-cart-sauce-labs-backpack"].
    - expect: Button's data-test changes to 'remove-sauce-labs-backpack' and its visible text changes to 'Remove'.
  3. Read [data-test="shopping-cart-badge"] text.
    - expect: Badge is now present and its text content is '1'.

#### 4.2. Removing a product reverts its button to Add to cart and decrements the badge; badge disappears at 0

**File:** `apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md`

**Steps:**
  1. Starting from the prior state with Sauce Labs Backpack added (badge='1'), click button[data-test="remove-sauce-labs-backpack"].
    - expect: Button's data-test reverts to 'add-to-cart-sauce-labs-backpack' and visible text reverts to 'Add to cart'.
  2. Assert [data-test="shopping-cart-badge"] is absent from the DOM.
    - expect: Badge is fully removed (not showing '0'); cart icon shows no count, matching the empty-cart state.

#### 4.3. Adding multiple products increments the badge correctly for each addition in any order

**File:** `apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md`

**Steps:**
  1. From an empty cart, click button[data-test="add-to-cart-sauce-labs-bike-light"].
    - expect: Badge shows '1'.
    - expect: Bike Light button becomes 'Remove' (data-test=remove-sauce-labs-bike-light).
  2. Click button[data-test="add-to-cart-sauce-labs-onesie"].
    - expect: Badge shows '2'.
    - expect: Onesie button becomes 'Remove' (data-test=remove-sauce-labs-onesie).
    - expect: Bike Light button remains 'Remove'.
  3. Click button[data-test="add-to-cart-sauce-labs-fleece-jacket"].
    - expect: Badge shows '3'.
    - expect: Fleece Jacket button becomes 'Remove' (data-test=remove-sauce-labs-fleece-jacket).
    - expect: Both previously added products remain in 'Remove' state.
  4. Click button[data-test="remove-sauce-labs-onesie"] to remove the middle-added item.
    - expect: Badge decrements to '2'.
    - expect: Onesie button reverts to 'Add to cart'.
    - expect: Bike Light and Fleece Jacket buttons remain 'Remove', unaffected by removing a different item.
  5. Click button[data-test="remove-sauce-labs-bike-light"] then button[data-test="remove-sauce-labs-fleece-jacket"].
    - expect: Badge decrements to '1' after the first removal, then the [data-test="shopping-cart-badge"] element is fully absent from the DOM after the second removal (back to empty cart).

#### 4.4. Add/remove button state and badge count survive a change of sort order

**File:** `apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md`

**Steps:**
  1. From an empty cart with default 'az' sort, click button[data-test="add-to-cart-sauce-labs-onesie"].
    - expect: Onesie button becomes 'Remove' (data-test=remove-sauce-labs-onesie).
    - expect: Badge shows '1'.
  2. Select option value 'za' on [data-test="product-sort-container"] to change sort order.
    - expect: Product order visibly changes (Z-to-A).
    - expect: Badge still shows '1' immediately after re-sort.
  3. Locate the Sauce Labs Onesie card by its name text (not position) in the new order and inspect its button.
    - expect: Button still shows 'Remove' with data-test='remove-sauce-labs-onesie' — add state was preserved across the sort change.
  4. Select option value 'lohi' on [data-test="product-sort-container"].
    - expect: Order changes again to ascending price.
    - expect: Onesie card (located by name) still shows 'Remove' and badge still shows '1'.
  5. With sort now 'lohi', click button[data-test="remove-sauce-labs-onesie"].
    - expect: Onesie button reverts to 'Add to cart'.
    - expect: [data-test="shopping-cart-badge"] is removed from the DOM (empty cart) — remove action also works correctly after a sort change.

#### 4.5. Negative: Add to cart button is not clickable twice to double-add the same product (no duplicate counting)

**File:** `apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md`

**Steps:**
  1. From an empty cart, click button[data-test="add-to-cart-sauce-labs-backpack"] once.
    - expect: Button becomes 'Remove' (data-test=remove-sauce-labs-backpack).
    - expect: Badge shows '1'.
  2. Attempt to locate button[data-test="add-to-cart-sauce-labs-backpack"] again on the same card.
    - expect: That locator no longer matches any element for this card (only the 'remove-sauce-labs-backpack' button exists now), confirming the UI prevents adding the same item twice via the catalog page.
    - expect: Badge remains '1', not '2'.

### 5. AC5 - Links to Product Details

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 5.1. Clicking a product's name link navigates to that product's detail page with matching id, name, and price

**File:** `apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md`

**Steps:**
  1. On the Products page, locate the inventory-item card whose [data-test="inventory-item-name"] text equals 'Sauce Labs Backpack' and read the data-test attribute of its name-link element (pattern item-<id>-title-link) to capture its id dynamically; also record the card's displayed price ('$29.99').
    - expect: A name-link matching [data-test^="item-"][data-test$="-title-link"] is found within the card, and an id (e.g. 4) is extracted from its data-test value.
  2. Click that name-link element.
    - expect: Browser navigates to a URL matching the pattern https://www.saucedemo.com/inventory-item.html?id=<the same id extracted above>.
  3. On the detail page, read [data-test="inventory-item-name"] and [data-test="inventory-item-price"].
    - expect: Name reads 'Sauce Labs Backpack' and price reads '$29.99', matching the product that was clicked on the listing page (not some other product).
  4. Click button[data-test="back-to-products"].
    - expect: Navigates back to https://www.saucedemo.com/inventory.html with all 6 products visible again.

#### 5.2. Clicking a product's image link navigates to the same detail page as its name link

**File:** `apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md`

**Steps:**
  1. On the Products page, locate the inventory-item card whose [data-test="inventory-item-name"] text equals 'Sauce Labs Bike Light' and read the data-test of its image-link element (pattern item-<id>-img-link) to capture its id dynamically.
    - expect: An image-link matching [data-test^="item-"][data-test$="-img-link"] is found within the card, and an id (e.g. 0) is extracted.
  2. Click the product image (the img-link element, not the name).
    - expect: Browser navigates to https://www.saucedemo.com/inventory-item.html?id=<the same id extracted above>.
  3. On the detail page, read [data-test="inventory-item-name"] and [data-test="inventory-item-price"].
    - expect: Name reads 'Sauce Labs Bike Light' and price reads '$9.99', confirming the image link routes to the correct product's detail page.
  4. Compare the id captured from the img-link in this test against the id that would be captured from the corresponding title-link for the same product (read both data-test attributes on the listing page without navigating).
    - expect: Both the title-link and img-link for the same product card reference the identical id value, proving name and image links are equivalent/consistent per product.

#### 5.3. Detail page links work correctly for every one of the 6 products (id uniqueness and correctness across the whole catalog)

**File:** `apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md`

**Steps:**
  1. On the Products page, for each of the 6 inventory-item cards, read the product's name, price, and the id embedded in its title-link data-test attribute (item-<id>-title-link).
    - expect: 6 (name, price, id) tuples are collected; all 6 id values are distinct from one another.
  2. For each of the 6 products in turn: navigate to https://www.saucedemo.com/inventory-item.html?id=<that product's id> directly (or click its name link), then read the detail page's [data-test="inventory-item-name"] and [data-test="inventory-item-price"], then navigate back to the Products page before testing the next product.
    - expect: For every product, the detail page's displayed name and price exactly match the name and price recorded for that id on the listing page — confirming no id collisions or mismatches anywhere in the catalog.

#### 5.4. Negative: navigating to the detail page URL with an invalid/out-of-range id does not crash and shows no matching product

**File:** `apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md`

**Steps:**
  1. Directly navigate to https://www.saucedemo.com/inventory-item.html?id=999 (an id known not to correspond to any of the 6 real products).
    - expect: Page loads without a hard browser error (no unhandled crash/blank fatal screen).
    - expect: [data-test="inventory-item-name"] is either absent or does not match any of the 6 valid product names, confirming the app does not silently display an unrelated/incorrect product for an invalid id.

#### 5.5. Name link and image link remain correct after changing sort order

**File:** `apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md`

**Steps:**
  1. On the Products page, select option value 'hilo' on [data-test="product-sort-container"] to reorder products by price descending.
    - expect: Product cards reorder on screen.
  2. Locate the card for 'Sauce Labs Fleece Jacket' by its name text in the new order, and click its name link.
    - expect: Navigates to /inventory-item.html?id=<Fleece Jacket's id>.
    - expect: Detail page shows name 'Sauce Labs Fleece Jacket' and price '$49.99', proving the link target is unaffected by the current sort order.
