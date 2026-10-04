# User Story: SCRUM-106 - Side Menu, App State and Footer

## Story Title
As a customer, I want a menu that takes me anywhere in the shop, lets me reset the shop and log out, so that I can move around and start over easily.

## Story Description
Every logged-in page has a header with a menu button ("Open Menu") and the cart icon, and a footer with social links. The side menu offers All Items, Dynamic Catalog (a submenu), About, Logout and Reset App State.

## Application URL
https://www.saucedemo.com (any logged-in page)

## Test Credentials
- Username: `standard_user`
- Password: `secret_sauce`

## Acceptance Criteria

### AC1: Opening and Closing the Menu
- WHEN I click "Open Menu"
- THEN the side menu should slide in with All Items, Dynamic Catalog, About, Logout and Reset App State
- WHEN I click "Close Menu" (X)
- THEN the menu should close
- AND the menu should work the same on the catalog, detail, cart and checkout pages

### AC2: All Items
- WHEN I choose "All Items" from any page (e.g. the cart or a detail page)
- THEN I should land on `/inventory.html`

### AC3: About
- The "About" item should link to `https://saucelabs.com/`
- Following it should leave the shop for the Sauce Labs website

### AC4: Reset App State
- GIVEN I have items in my cart
- WHEN I choose "Reset App State"
- THEN the cart badge should disappear
- AND after a reload the cart should be empty and every product should show "Add to cart"
- AND I should stay logged in

### AC5: Footer and Logout
- The footer should show X, Facebook and LinkedIn links to `https://x.com/saucelabs`, `https://www.facebook.com/saucelabs` and `https://www.linkedin.com/company/sauce-labs/`, plus the "© <year> Sauce Labs. All Rights Reserved." notice
- "Logout" from the menu should return me to the login page (login details are covered by SCRUM-102)

## Business Rules
1. The menu and footer are the same on every logged-in page
2. Reset App State empties the cart without logging out
3. External links leave the shop. They are not part of the shop's own flows

## Technical Notes
- Use Playwright for test automation
- Test across Chrome, Firefox, Safari and a mobile viewport
- Open the menu with `getByRole('button', { name: 'Open Menu' })` and close it with `getByRole('button', { name: 'Close Menu' })`. Clicking `[data-test="open-menu"]` times out because the button sits on top of that image. Opening it via a JavaScript click leaves the items `aria-hidden` (see README Gotchas)
- Menu item locators: `inventory-sidebar-link`, `dynamic-catalog-sidebar-link`, `about-sidebar-link`, `logout-sidebar-link`, `reset-sidebar-link`. Footer: `social-x`, `social-facebook`, `social-linkedin`, `footer-copy`
- The menu slides in with an animation. Wait for the item to be visible before clicking it
- Observed quirk: after Reset App State the cart page and the catalog's "Remove" buttons don't update until a reload. Record this as an observation; assert the reset state after a reload
- For About and the social links, assert the `href` (and, if you follow the link, the URL only), so the suite doesn't depend on third-party sites being up
- The Dynamic Catalog pages are covered by SCRUM-107

## Definition of Done
- [ ] All acceptance criteria have test cases
- [ ] Manual exploratory testing completed
- [ ] Automated test scripts created and passing
- [ ] Test results documented
- [ ] Bugs logged for any failures
- [ ] Code committed to repository
