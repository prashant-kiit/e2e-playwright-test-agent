# User Story: SCRUM-103 - Product Catalog and Sorting

## Story Title
As a customer, I want to see all products and sort them so that I can find what I want.

## Story Description
The Products page lists every product and a sort dropdown reorders them. (Trimmed scope: the listing plus price sorting.)

## Application URL
https://www.saucedemo.com/inventory.html

## Test Credentials
- Username: `standard_user`
- Password: `secret_sauce`

## Acceptance Criteria

### AC1: Product Listing (happy path)
- GIVEN I am logged in on the Products page
- THEN I should see 6 products, each with a name, price and an "Add to cart" button
- AND the default sort should be "Name (A to Z)" with the names in ascending order

### AC2: Sort by Price (key behavior)
- WHEN I choose "Price (low to high)" in the sort dropdown
- THEN the products should be ordered by ascending price
- AND choosing "Price (high to low)" should reverse that order

## Business Rules
1. All 6 products are always listed (no paging or filtering)
2. Sorting changes only the order, not the contents

## Technical Notes
- Use Playwright. Locators use `data-test` attributes: `inventory-item`, `inventory-item-name`, `inventory-item-price`, `product-sort-container` (values `az`, `za`, `lohi`, `hilo`), `active-option`
- Verify sorting by reading all names/prices and comparing with a sorted copy, not by hard-coding positions
- The agent generates and heals on Chromium only to save tokens; the target repo's CI runs the suite on all browser projects

## Definition of Done
- [ ] Acceptance criteria have test cases
- [ ] Automated test scripts created and passing on Chromium
- [ ] Test results documented
- [ ] Code committed to repository
