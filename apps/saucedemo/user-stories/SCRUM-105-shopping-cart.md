# User Story: SCRUM-105 - Shopping Cart

## Story Title
As a customer, I want my cart to track what I've added so that I don't lose my selection.

## Story Description
The cart badge counts items and the cart page lists them. (Trimmed scope: adding/listing, plus removing.)

## Application URL
https://www.saucedemo.com (pages: `/inventory.html`, `/cart.html`)

## Test Credentials
- Username: `standard_user`
- Password: `secret_sauce`

## Acceptance Criteria

### AC1: Add and View (happy path)
- GIVEN an empty cart (no badge)
- WHEN I add two products and open the cart
- THEN the badge should read 2 and `/cart.html` should list both items, each with quantity 1, name and price

### AC2: Remove (key behavior)
- WHEN I click "Remove" on a cart item
- THEN it should disappear from the list and the badge should decrease by 1
- AND the product's catalog button should read "Add to cart" again

## Business Rules
1. The badge count equals the number of cart items
2. Each product is in the cart at most once (quantity 1)

## Technical Notes
- Use Playwright. Locators use `data-test` attributes: `add-to-cart-<slug>`, `remove-<slug>`, `shopping-cart-link`, `shopping-cart-badge`, `cart-list`, `inventory-item`, `item-quantity`, `inventory-item-name`, `inventory-item-price`
- Each Playwright test gets a fresh context, so tests start with an empty cart
- The agent generates and heals on Chromium only to save tokens; the target repo's CI runs the suite on all browser projects

## Definition of Done
- [ ] Acceptance criteria have test cases
- [ ] Automated test scripts created and passing on Chromium
- [ ] Test results documented
- [ ] Code committed to repository
