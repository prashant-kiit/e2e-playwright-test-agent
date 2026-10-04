# User Story: SCRUM-103 - Product Catalog and Sorting

## Story Title
As a customer, I want to browse all products and sort them by name or price so that I can find what I want quickly.

## Story Description
After login the customer lands on the Products page, which lists every product with an image, name, description, price and an "Add to cart" button. A sort dropdown reorders the list. Product names and images link to each product's detail page.

## Application URL
https://www.saucedemo.com (page: `/inventory.html`)

## Test Credentials
- Username: `standard_user`
- Password: `secret_sauce`

## Acceptance Criteria

### AC1: Product Listing
- GIVEN I am logged in
- WHEN I open the Products page
- THEN I should see 6 products: Sauce Labs Backpack ($29.99), Sauce Labs Bike Light ($9.99), Sauce Labs Bolt T-Shirt ($15.99), Sauce Labs Fleece Jacket ($49.99), Sauce Labs Onesie ($7.99) and Test.allTheThings() T-Shirt (Red) ($15.99)
- AND each product should show an image, name, description, price and an "Add to cart" button

### AC2: Default Sort
- The sort dropdown should show "Name (A to Z)" by default
- The products should be listed alphabetically by name

### AC3: Sorting Options
- The dropdown should offer Name (A to Z), Name (Z to A), Price (low to high) and Price (high to low)
- Choosing each option should reorder the list accordingly, and the dropdown should show the chosen option
- For equal prices (the two $15.99 T-shirts), either order is acceptable

### AC4: Add and Remove from the List
- WHEN I click "Add to cart" on a product
- THEN its button should change to "Remove" and the cart badge should increase by 1
- WHEN I click "Remove"
- THEN the button should change back to "Add to cart" and the badge should decrease by 1 (and disappear at 0)
- AND the button state should survive a change of sort order

### AC5: Links to Product Details
- Clicking a product's name or image should open its detail page (`/inventory-item.html?id=<n>`) for that product

## Business Rules
1. All products are always listed. There is no paging or filtering
2. Sorting changes only the order, never the contents
3. The add/remove state of each product matches the cart

## Technical Notes
- Use Playwright for test automation
- Test across Chrome, Firefox, Safari and a mobile viewport
- Locators use `data-test` attributes: `title`, `inventory-list`, `inventory-item`, `inventory-item-name`, `inventory-item-desc`, `inventory-item-price`, `product-sort-container` (values `az`, `za`, `lohi`, `hilo`), `active-option`, `add-to-cart-<product-slug>`, `remove-<product-slug>`, `shopping-cart-badge`, `item-<id>-title-link`, `item-<id>-img-link`
- Product slugs are the lower-case name with spaces replaced by `-` (e.g. `sauce-labs-backpack`, `test.allthethings()-t-shirt-(red)`)
- Verify sorting by reading all names or prices and comparing them with a sorted copy, not by hard-coding positions
- The seed logs in and lands on this page

## Definition of Done
- [ ] All acceptance criteria have test cases
- [ ] Manual exploratory testing completed
- [ ] Automated test scripts created and passing
- [ ] Test results documented
- [ ] Bugs logged for any failures
- [ ] Code committed to repository
