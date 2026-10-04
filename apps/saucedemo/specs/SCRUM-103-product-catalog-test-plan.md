# SCRUM-103 Product Catalog and Sorting Test Plan

## Application Overview

SauceDemo (https://www.saucedemo.com) is a demo e-commerce site used for test automation practice. This plan covers SCRUM-103 "Product Catalog and Sorting" — the inventory page (`/inventory.html`) reached after logging in as `standard_user` / `secret_sauce`. The page lists 6 fixed products, each with an image, name, description, price, and an Add to cart / Remove toggle button. A sort dropdown (`product-sort-container`) reorders the list by name or price. Clicking a product's name or image navigates to its detail page (`/inventory-item.html?id=<n>`). A cart badge (`shopping-cart-badge`) reflects the number of items added across the app. All test cases assume a fresh app session: the provided seed file logs in and lands on `/inventory.html` with an empty cart and default "Name (A to Z)" sort — no prior state carries over between independent test cases (each test should perform its own login via the seed and must not rely on execution order).

Confirmed stable locators (via `[data-test="..."]`):
- Product cards: `inventory-list`, `inventory-item` (6 total)
- Per item: `inventory-item-name`, `inventory-item-desc`, `inventory-item-price`, image `inventory-item-<slug>-img`
- Add/remove buttons on the list page: `add-to-cart-<slug>` / `remove-<slug>` where slug = lowercase name with spaces→`-` (e.g. `sauce-labs-backpack`, `test.allthethings()-t-shirt-(red)`)
- Name/Image links on the list page: `item-<id>-title-link`, `item-<id>-img-link` where `<id>` is the product's fixed internal id (NOT its sort position): Sauce Labs Backpack=4, Sauce Labs Bike Light=0, Sauce Labs Bolt T-Shirt=1, Test.allTheThings() T-Shirt (Red)=3, Sauce Labs Onesie=2, Sauce Labs Fleece Jacket=5. These anchors have `href="#"` — navigation is JS-driven, so assertions must be on `page.url()` after click, not on the href attribute.
- Cart badge: `shopping-cart-badge` (absent entirely, not just empty text, when cart has 0 items)
- Sort dropdown: `product-sort-container` is a `<select>` with options value `az`/`za`/`lohi`/`hilo` and visible text "Name (A to Z)" / "Name (Z to A)" / "Price (low to high)" / "Price (high to low)"; the currently selected label is also mirrored in a separate `active-option` element
- Detail page (`/inventory-item.html?id=<n>`): `back-to-products` button returns to `/inventory.html`; the add-to-cart button here has data-test `add-to-cart` (no slug suffix, since there is only one product in context)

Fixed catalog data used throughout:
| Product | Price | Internal id |
|---|---|---|
| Sauce Labs Backpack | $29.99 | 4 |
| Sauce Labs Bike Light | $9.99 | 0 |
| Sauce Labs Bolt T-Shirt | $15.99 | 1 |
| Sauce Labs Fleece Jacket | $49.99 | 5 |
| Sauce Labs Onesie | $7.99 | 2 |
| Test.allTheThings() T-Shirt (Red) | $15.99 | 3 |

Note: Sauce Labs Bolt T-Shirt and Test.allTheThings() T-Shirt (Red) both cost $15.99, so when sorting by price, either relative order between these two is acceptable — tests must tolerate both orderings and only assert strict ordering on price value, with name used only as a secondary/non-strict check for this pair.

## Test Scenarios

### 1. Product Listing (AC1)

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 1.1. Inventory page displays exactly 6 products with complete information

**File:** `apps/saucedemo/tests/product-catalog/product-listing.spec.ts`

**Steps:**
  1. Start from the seed file (logged in, on /inventory.html).
    - expect: Page URL is https://www.saucedemo.com/inventory.html
    - expect: Page title element [data-test="title"] shows 'Products'
  2. Locate [data-test="inventory-list"] and count child elements matching [data-test="inventory-item"].
    - expect: Exactly 6 inventory-item elements are present
  3. For each of the 6 expected products (Sauce Labs Backpack, Sauce Labs Bike Light, Sauce Labs Bolt T-Shirt, Sauce Labs Fleece Jacket, Sauce Labs Onesie, Test.allTheThings() T-Shirt (Red)), locate its inventory-item card by matching [data-test="inventory-item-name"] text.
    - expect: Each named product is found exactly once among the 6 cards
  4. Within each located card, assert presence of an <img> element, [data-test="inventory-item-desc"] with non-empty text, [data-test="inventory-item-price"], and a button whose data-test starts with 'add-to-cart-'.
    - expect: All four elements exist and are visible for every one of the 6 products
  5. Read the text of [data-test="inventory-item-price"] for each of the 6 named products and compare to expected values.
    - expect: Sauce Labs Backpack = $29.99
    - expect: Sauce Labs Bike Light = $9.99
    - expect: Sauce Labs Bolt T-Shirt = $15.99
    - expect: Sauce Labs Fleece Jacket = $49.99
    - expect: Sauce Labs Onesie = $7.99
    - expect: Test.allTheThings() T-Shirt (Red) = $15.99
  6. Assert the Add to cart buttons are all enabled/clickable and none show 'Remove' (i.e. cart starts empty for a fresh session).
    - expect: All 6 buttons read 'Add to cart'
    - expect: [data-test="shopping-cart-badge"] is not present in the DOM

#### 1.2. Each product image is distinct and associated with the correct product name

**File:** `apps/saucedemo/tests/product-catalog/product-listing.spec.ts`

**Steps:**
  1. Start from the seed file.
    - expect: On /inventory.html with 6 products visible
  2. For each inventory-item card, read the img element's alt attribute and the sibling [data-test="inventory-item-name"] text.
    - expect: img alt text matches the product name text for every card (e.g. img alt 'Sauce Labs Backpack' pairs with name text 'Sauce Labs Backpack')
  3. Collect the 6 img src attributes.
    - expect: No two products share an identical image src value (each product has a distinct image), OR if duplicates exist (known SauceDemo quirk where some demo images repeat), the test should only assert that each img element loads successfully (naturalWidth > 0) rather than fail on src uniqueness

### 2. Default Sort (AC2)

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 2.1. Dropdown defaults to Name (A to Z) and list is alphabetically sorted on load

**File:** `apps/saucedemo/tests/product-catalog/default-sort.spec.ts`

**Steps:**
  1. Start from the seed file, freshly on /inventory.html without touching the sort dropdown.
    - expect: Page loaded with no prior interaction
  2. Read the selected option's visible text from [data-test="product-sort-container"] (e.g. via selectedOptions or the displayed value).
    - expect: Selected option text is exactly 'Name (A to Z)' and its value attribute is 'az'
  3. Read [data-test="active-option"] text.
    - expect: Shows 'Name (A to Z)'
  4. Read all 6 [data-test="inventory-item-name"] texts in DOM order into an array.
    - expect: Array equals ['Sauce Labs Backpack','Sauce Labs Bike Light','Sauce Labs Bolt T-Shirt','Sauce Labs Fleece Jacket','Sauce Labs Onesie','Test.allTheThings() T-Shirt (Red)'], i.e. already alphabetically sorted
  5. Independently verify by sorting a copy of the captured name array alphabetically (locale/ASCII compare) and diffing against the captured order — do not hard-code the comparison result.
    - expect: Captured order matches the sorted copy exactly

### 3. Sorting Options (AC3)

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 3.1. Sort dropdown exposes all four expected options with correct values and labels

**File:** `apps/saucedemo/tests/product-catalog/sorting.spec.ts`

**Steps:**
  1. Start from the seed file.
    - expect: On /inventory.html
  2. Query all <option> elements inside [data-test="product-sort-container"] and capture their value and text.
    - expect: Exactly 4 options present: value='az' text='Name (A to Z)'; value='za' text='Name (Z to A)'; value='lohi' text='Price (low to high)'; value='hilo' text='Price (high to low)', in that order

#### 3.2. Selecting Name (Z to A) reorders products reverse-alphabetically

**File:** `apps/saucedemo/tests/product-catalog/sorting.spec.ts`

**Steps:**
  1. Start from the seed file. Capture the current list of 6 product names before sorting.
    - expect: Baseline alphabetical order captured
  2. Use selectOption on [data-test="product-sort-container"] with value 'za'.
    - expect: No errors thrown
  3. Read [data-test="active-option"] text.
    - expect: Shows 'Name (Z to A)'
  4. Read the 6 product names in DOM order after sorting.
    - expect: Order equals the baseline array reversed
  5. Programmatically sort a copy of the baseline names descending (not hard-coded positions) and compare to the captured post-sort order.
    - expect: Captured order matches the computed descending sort exactly

#### 3.3. Selecting Price (low to high) reorders products by ascending price

**File:** `apps/saucedemo/tests/product-catalog/sorting.spec.ts`

**Steps:**
  1. Start from the seed file.
    - expect: On /inventory.html, default az sort
  2. Use selectOption on [data-test="product-sort-container"] with value 'lohi'.
    - expect: No errors thrown
  3. Read [data-test="active-option"] text.
    - expect: Shows 'Price (low to high)'
  4. Parse the [data-test="inventory-item-price"] text for all 6 cards (strip '$', convert to number) in DOM order.
    - expect: Resulting numeric array equals [7.99, 9.99, 15.99, 15.99, 29.99, 49.99], i.e. non-decreasing
  5. Assert programmatically (via Array.every that each element <= the next) that the captured price array is non-decreasing, without hard-coding exact positions.
    - expect: Assertion passes
  6. Identify the two cards with price 15.99 and read their names.
    - expect: The pair is {Sauce Labs Bolt T-Shirt, Test.allTheThings() T-Shirt (Red)} in either relative order — test must not fail based on which of the two comes first

#### 3.4. Selecting Price (high to low) reorders products by descending price

**File:** `apps/saucedemo/tests/product-catalog/sorting.spec.ts`

**Steps:**
  1. Start from the seed file.
    - expect: On /inventory.html, default az sort
  2. Use selectOption on [data-test="product-sort-container"] with value 'hilo'.
    - expect: No errors thrown
  3. Read [data-test="active-option"] text.
    - expect: Shows 'Price (high to low)'
  4. Parse the price text for all 6 cards in DOM order into numbers.
    - expect: Resulting numeric array equals [49.99, 29.99, 15.99, 15.99, 9.99, 7.99], i.e. non-increasing
  5. Assert programmatically that the captured price array is non-increasing (each element >= the next), without hard-coding exact positions.
    - expect: Assertion passes
  6. Identify the two cards with price 15.99 and read their names.
    - expect: The pair is {Sauce Labs Bolt T-Shirt, Test.allTheThings() T-Shirt (Red)} in either relative order — test must not fail based on which of the two comes first

#### 3.5. Switching between multiple sort options in sequence keeps list and active-option label consistent

**File:** `apps/saucedemo/tests/product-catalog/sorting.spec.ts`

**Steps:**
  1. Start from the seed file.
    - expect: Default az sort active
  2. Select 'za', then read names and active-option.
    - expect: Names are descending alphabetical; active-option = 'Name (Z to A)'
  3. Select 'lohi', then read prices and active-option.
    - expect: Prices non-decreasing; active-option = 'Price (low to high)'
  4. Select 'hilo', then read prices and active-option.
    - expect: Prices non-increasing; active-option = 'Price (high to low)'
  5. Select 'az' again, then read names and active-option.
    - expect: Names ascending alphabetical again; active-option = 'Name (A to Z)'; list returns to the original default order

### 4. Add and Remove from List (AC4)

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 4.1. Adding a single product updates its button to Remove and increments the badge

**File:** `apps/saucedemo/tests/product-catalog/add-remove.spec.ts`

**Steps:**
  1. Start from the seed file. Assert [data-test="shopping-cart-badge"] is absent.
    - expect: No badge present, cart is empty
  2. Click [data-test="add-to-cart-sauce-labs-backpack"].
    - expect: Button's data-test becomes 'remove-sauce-labs-backpack' and its visible text becomes 'Remove'
  3. Read [data-test="shopping-cart-badge"] text.
    - expect: Badge is present and shows '1'

#### 4.2. Removing a product reverts its button and decrements the badge to zero (badge disappears)

**File:** `apps/saucedemo/tests/product-catalog/add-remove.spec.ts`

**Steps:**
  1. Start from the seed file. Click [data-test="add-to-cart-sauce-labs-backpack"] to add the item first.
    - expect: Badge shows '1', button shows 'Remove'
  2. Click [data-test="remove-sauce-labs-backpack"].
    - expect: Button's data-test reverts to 'add-to-cart-sauce-labs-backpack' and visible text reverts to 'Add to cart'
  3. Query [data-test="shopping-cart-badge"].
    - expect: Element is not present in the DOM at all (not merely empty text) confirming badge fully disappears at 0 items

#### 4.3. Adding multiple distinct products increments the badge cumulatively

**File:** `apps/saucedemo/tests/product-catalog/add-remove.spec.ts`

**Steps:**
  1. Start from the seed file.
    - expect: Badge absent
  2. Click [data-test="add-to-cart-sauce-labs-backpack"].
    - expect: Badge shows '1'
  3. Click [data-test="add-to-cart-sauce-labs-onesie"].
    - expect: Badge shows '2'
  4. Click [data-test="add-to-cart-sauce-labs-bike-light"].
    - expect: Badge shows '3'
  5. Verify all three corresponding buttons now read 'Remove' with the correct remove-<slug> data-test, while the other 3 unaffected products still show 'Add to cart'.
    - expect: Backpack, Onesie, Bike Light show Remove; Bolt T-Shirt, Fleece Jacket, Test.allTheThings() T-Shirt (Red) still show Add to cart
  6. Click remove-sauce-labs-onesie.
    - expect: Badge decrements to '2', Onesie button reverts to Add to cart, the other two Remove buttons remain unaffected

#### 4.4. Add-to-cart button state for an item survives changing the sort order

**File:** `apps/saucedemo/tests/product-catalog/add-remove.spec.ts`

**Steps:**
  1. Start from the seed file. Click [data-test="add-to-cart-sauce-labs-backpack"] to add Backpack to the cart.
    - expect: Backpack button shows 'Remove'; badge shows '1'
  2. Select 'hilo' (Price high to low) on [data-test="product-sort-container"].
    - expect: List reorders by descending price; active-option shows 'Price (high to low)'
  3. Locate the Sauce Labs Backpack card again (now at a different position) and inspect its button.
    - expect: Button is still [data-test="remove-sauce-labs-backpack"] reading 'Remove' — state persisted across resort
    - expect: Badge still shows '1'
  4. Select 'za' (Name Z to A) on the sort dropdown.
    - expect: List reorders reverse-alphabetically
  5. Locate the Backpack card again.
    - expect: Still shows 'Remove', badge still '1', confirming cart state is independent of sort order across multiple resorts
  6. Click the Backpack's Remove button in this new sort position.
    - expect: Button reverts to 'Add to cart'; badge element disappears from DOM (0 items)

### 5. Links to Product Details (AC5)

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 5.1. Clicking a product name navigates to that product's detail page

**File:** `apps/saucedemo/tests/product-catalog/product-details.spec.ts`

**Steps:**
  1. Start from the seed file, default az sort. Click [data-test="item-4-title-link"] (the Sauce Labs Backpack name).
    - expect: Browser navigates to https://www.saucedemo.com/inventory-item.html?id=4
  2. On the detail page, read the product name/price elements.
    - expect: Displayed name is 'Sauce Labs Backpack' and price is '$29.99', matching the clicked product from the list
  3. Click [data-test="back-to-products"].
    - expect: Navigates back to https://www.saucedemo.com/inventory.html with the full 6-item list visible again

#### 5.2. Clicking a product image navigates to that product's detail page

**File:** `apps/saucedemo/tests/product-catalog/product-details.spec.ts`

**Steps:**
  1. Start from the seed file. Click [data-test="item-0-img-link"] (the Sauce Labs Bike Light image).
    - expect: Browser navigates to https://www.saucedemo.com/inventory-item.html?id=0
  2. On the detail page, read the product name/price elements.
    - expect: Displayed name is 'Sauce Labs Bike Light' and price is '$9.99'
  3. Click [data-test="back-to-products"] to return.
    - expect: Back on /inventory.html

#### 5.3. Each of the 6 products' name and image links both resolve to the same, correct detail id

**File:** `apps/saucedemo/tests/product-catalog/product-details.spec.ts`

**Steps:**
  1. Start from the seed file. For each of the 6 known (slug/id) pairs — bike-light=0, bolt-t-shirt=1, onesie=2, allthethings-t-shirt=3, backpack=4, fleece-jacket=5 — click [data-test="item-<id>-title-link"], capture the resulting URL, then navigate back via [data-test="back-to-products"].
    - expect: Each click results in URL /inventory-item.html?id=<the matching id> and the detail heading matches the expected product name for every one of the 6 products
  2. Repeat the same loop but clicking [data-test="item-<id>-img-link"] instead of the title link for each product.
    - expect: Each image-link click also results in the same /inventory-item.html?id=<id> URL and matching product name, confirming name and image links are equivalent/consistent for every product

#### 5.4. Add to cart from the detail page reflects back on the inventory list

**File:** `apps/saucedemo/tests/product-catalog/product-details.spec.ts`

**Steps:**
  1. Start from the seed file. Click [data-test="item-4-title-link"] to open the Sauce Labs Backpack detail page.
    - expect: On /inventory-item.html?id=4
  2. Click the detail page's [data-test="add-to-cart"] button.
    - expect: Button becomes [data-test="remove"] / text 'Remove'; cart badge shows '1' on the detail page header
  3. Click [data-test="back-to-products"] to return to the list.
    - expect: On /inventory.html
  4. Locate the Sauce Labs Backpack card.
    - expect: Its button is [data-test="remove-sauce-labs-backpack"] showing 'Remove', and [data-test="shopping-cart-badge"] still shows '1', confirming cart state added on the detail page is reflected on the list view
