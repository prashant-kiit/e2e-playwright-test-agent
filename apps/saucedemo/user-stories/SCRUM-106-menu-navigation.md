# User Story: SCRUM-106 - Side Menu and App State

## Story Title
As a customer, I want the side menu to move me around and reset the shop so that I can start over.

## Story Description
Every logged-in page has a side menu with All Items, Reset App State and Logout. (Trimmed scope: navigation via the menu, plus Reset App State.)

## Application URL
https://www.saucedemo.com (any logged-in page)

## Test Credentials
- Username: `standard_user`
- Password: `secret_sauce`

## Acceptance Criteria

### AC1: Menu Navigation (happy path)
- WHEN I open the menu from a non-inventory page (e.g. the cart) and click "All Items"
- THEN I should land on `/inventory.html`

### AC2: Reset App State (key behavior)
- GIVEN I have items in my cart
- WHEN I open the menu and click "Reset App State", then reload
- THEN the cart should be empty, every product should show "Add to cart", and I should stay logged in

## Business Rules
1. Reset App State empties the cart without logging out

## Technical Notes
- Use Playwright. Open the menu with `getByRole('button', { name: 'Open Menu' })`; clicking `[data-test="open-menu"]` times out (the button covers it) and a JS click leaves the items `aria-hidden`
- Locators: `inventory-sidebar-link`, `reset-sidebar-link`, `shopping-cart-badge`, `add-to-cart-<slug>`
- Observed quirk: after Reset App State the badge clears but the catalog/cart don't update until a reload; assert the reset state after reloading
- The agent generates and heals on Chromium only to save tokens; the target repo's CI runs the suite on all browser projects

## Definition of Done
- [ ] Acceptance criteria have test cases
- [ ] Automated test scripts created and passing on Chromium
- [ ] Test results documented
- [ ] Code committed to repository
