# User Story: SCRUM-104 - Product Details Page

## Story Title
As a customer, I want each product's detail page so that I can review it and add it to my cart.

## Story Description
Each product has a detail page with its name, description, price and an add/remove button. (Trimmed scope: the detail content/add, plus the unknown-product case.)

## Application URL
https://www.saucedemo.com/inventory-item.html?id=<n>

## Test Credentials
- Username: `standard_user`
- Password: `secret_sauce`

## Acceptance Criteria

### AC1: Detail Content and Add to Cart (happy path)
- GIVEN I open a product from the catalog
- THEN its detail page should show the same name, description and price as the catalog
- WHEN I click "Add to cart"
- THEN the button should change to "Remove" and the cart badge should increase by 1
- AND "Back to products" should return to `/inventory.html`

### AC2: Unknown Product (key negative)
- WHEN I open `/inventory-item.html?id=999` (an id that doesn't exist)
- THEN the page should show "ITEM NOT FOUND" instead of a product

## Business Rules
1. The detail page and the catalog show the same data for a product

## Technical Notes
- Use Playwright. Locators use `data-test` attributes: `inventory-item-name`, `inventory-item-desc`, `inventory-item-price`, `add-to-cart`, `remove`, `back-to-products`, `shopping-cart-badge`
- Product ids are not in list order (e.g. Backpack is `id=4`); navigate by clicking a product rather than assuming an order
- The agent generates and heals on Chromium only to save tokens; the target repo's CI runs the suite on all browser projects

## Definition of Done
- [ ] Acceptance criteria have test cases
- [ ] Automated test scripts created and passing on Chromium
- [ ] Test results documented
- [ ] Code committed to repository
