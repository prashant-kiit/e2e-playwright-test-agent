# User Story: SCRUM-104 - Product Details Page

## Story Title
As a customer, I want to see a product's full details on its own page and add it to my cart from there so that I can decide before buying.

## Story Description
Each product has a detail page at `/inventory-item.html?id=<n>` with a large image, the name, the full description, the price and an add/remove button. A "Back to products" button returns to the catalog.

## Application URL
https://www.saucedemo.com (page: `/inventory-item.html?id=<n>`)

## Test Credentials
- Username: `standard_user`
- Password: `secret_sauce`

## Acceptance Criteria

### AC1: Detail Content
- GIVEN I am on the Products page
- WHEN I open a product's detail page
- THEN I should see the same name, description and price as in the catalog, plus the product image
- AND this should hold for every one of the 6 products

### AC2: Add and Remove from the Detail Page
- WHEN I click "Add to cart" on the detail page
- THEN the button should change to "Remove" and the cart badge should increase by 1
- WHEN I click "Remove"
- THEN the button should change back to "Add to cart" and the badge should decrease
- AND a product already in the cart should show "Remove" when its detail page opens

### AC3: Back to Products
- WHEN I click "Back to products"
- THEN I should return to `/inventory.html`
- AND the catalog buttons should reflect any change made on the detail page

### AC4: Direct Links
- Opening `/inventory-item.html?id=<n>` directly while logged in should show that product
- Opening it while logged out should send me to the login page with the protected-page error

### AC5: Unknown Product
- WHEN I open a detail URL with an id that doesn't exist (e.g. `?id=999`)
- THEN the page should show "ITEM NOT FOUND" instead of a product
- AND "Back to products" should still work

## Business Rules
1. The detail page and the catalog always show the same data for a product
2. Cart changes made on the detail page apply everywhere

## Technical Notes
- Use Playwright for test automation
- Test across Chrome, Firefox, Safari and a mobile viewport
- Locators use `data-test` attributes: `inventory-item-name`, `inventory-item-desc`, `inventory-item-price`, `add-to-cart`, `remove`, `back-to-products`, `shopping-cart-badge`, `item-<id>-title-link`. On this page the add/remove buttons have no product slug
- Product ids are not in list order (e.g. Backpack is `id=4`). Navigate by clicking a product, or read the id from the link, rather than assuming an order
- How the "ITEM NOT FOUND" page looks is not specified. If exploration finds odd behaviour there, record it as an observation

## Definition of Done
- [ ] All acceptance criteria have test cases
- [ ] Manual exploratory testing completed
- [ ] Automated test scripts created and passing
- [ ] Test results documented
- [ ] Bugs logged for any failures
- [ ] Code committed to repository
