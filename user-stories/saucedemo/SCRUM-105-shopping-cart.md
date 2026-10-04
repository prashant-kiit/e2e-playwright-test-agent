# User Story: SCRUM-105 - Shopping Cart

## Story Title
As a customer, I want my cart to keep track of what I've added, across pages and reloads, so that I don't lose my selection before checkout.

## Story Description
The cart icon in the header shows a badge with the number of items. The cart page lists each item with its quantity, name, description and price, and lets the customer remove items, continue shopping or go to checkout. The cart is stored in the browser, so it survives page reloads, and it is emptied when the customer logs out. (The checkout steps after the cart are covered by SCRUM-101.)

## Application URL
https://www.saucedemo.com (pages: `/inventory.html`, `/cart.html`)

## Test Credentials
- Username: `standard_user`
- Password: `secret_sauce`

## Acceptance Criteria

### AC1: Cart Badge
- With an empty cart, the cart icon should show no badge
- Adding items should show a badge with the item count, and removing items should lower it
- The badge should disappear when the cart is empty again

### AC2: Cart Contents
- GIVEN I have added items
- WHEN I click the cart icon
- THEN I should land on `/cart.html` titled "Your Cart"
- AND each added item should be listed with quantity 1, its name, description and price
- AND the items should match exactly what I added (no more, no less)

### AC3: Removing Items in the Cart
- WHEN I click "Remove" on a cart item
- THEN it should disappear from the list immediately and the badge should decrease
- AND the product's catalog button should read "Add to cart" again

### AC4: Persistence
- The cart should keep its contents when I reload the page
- The cart should keep its contents when I move between the catalog, detail pages and the cart page
- The cart should be emptied when I log out and log back in

### AC5: Navigation from the Cart
- "Continue Shopping" should return to `/inventory.html` with the cart unchanged
- "Checkout" should open `/checkout-step-one.html`

## Business Rules
1. Each product can be in the cart at most once (quantity is always 1)
2. The badge count always equals the number of cart items
3. The cart is saved in the browser and cleared on logout

## Technical Notes
- Use Playwright for test automation
- Test across Chrome, Firefox, Safari and a mobile viewport
- Locators use `data-test` attributes: `shopping-cart-link`, `shopping-cart-badge`, `cart-list`, `inventory-item`, `item-quantity`, `inventory-item-name`, `inventory-item-desc`, `inventory-item-price`, `remove-<product-slug>`, `add-to-cart-<product-slug>`, `continue-shopping`, `checkout`
- The cart is stored in `localStorage` under `cart-contents` (a list of product ids). Each Playwright test gets a fresh context, so tests start with an empty cart
- Observed quirk: "Reset App State" in the menu clears the badge, but the cart page keeps listing items until it is reloaded. That belongs to SCRUM-106; don't use Reset App State to set up cart tests
- Overlap with SCRUM-101 AC1 (cart review during checkout) is expected. This story covers cart state, not the checkout flow

## Definition of Done
- [ ] All acceptance criteria have test cases
- [ ] Manual exploratory testing completed
- [ ] Automated test scripts created and passing
- [ ] Test results documented
- [ ] Bugs logged for any failures
- [ ] Code committed to repository
