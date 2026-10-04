# User Story: SCRUM-101 - E-commerce Checkout Process

## Story Title
As a customer, I want to complete my purchase through checkout so that I can order products online.

## Story Description
From a cart with items, the customer goes through checkout information, an order overview with totals, and an order confirmation. (Trimmed scope: happy path end to end, plus mandatory-field validation.)

## Application URL
https://www.saucedemo.com

## Test Credentials
- Username: `standard_user`
- Password: `secret_sauce`

## Acceptance Criteria

### AC1: Complete a Purchase (happy path)
- GIVEN I am logged in with an item in my cart
- WHEN I open the cart, click Checkout, enter First Name, Last Name and Zip, click Continue, then click Finish
- THEN each step should advance (cart → `/checkout-step-one.html` → `/checkout-step-two.html` → `/checkout-complete.html`)
- AND the overview should show item total, tax and a total equal to item total + tax
- AND the confirmation page should show "Thank you for your order!" and a Back Home button
- AND the cart badge should be cleared after completion

### AC2: Mandatory Field Validation (key negative)
- GIVEN I am on the checkout information page with all fields empty
- WHEN I click Continue
- THEN I should see the error "Error: First Name is required" and stay on the page
- AND filling First Name then continuing with Last Name empty should show "Error: Last Name is required"

## Business Rules
1. All three checkout fields are mandatory
2. Order confirmation clears the cart

## Technical Notes
- Use Playwright. Locators use `data-test` attributes: `add-to-cart-sauce-labs-backpack`, `shopping-cart-link`, `checkout`, `firstName`, `lastName`, `postalCode`, `continue`, `finish`, `error`, `complete-header`, `back-to-products`, `shopping-cart-badge`
- Relative URLs (baseURL is in playwright.config.ts)
- The agent generates and heals on Chromium only to save tokens; the target repo's CI runs the suite on all browser projects

## Definition of Done
- [ ] Acceptance criteria have test cases
- [ ] Automated test scripts created and passing on Chromium
- [ ] Test results documented
- [ ] Code committed to repository
