# User Story: SCRUM-107 - Dynamic Catalog Views

## Story Title
As a customer, I want alternative catalog views that load products dynamically so that browsing stays engaging.

## Story Description
The menu's Dynamic Catalog submenu opens Lazy Load, Spinner and Slider views. (Trimmed scope: the Spinner view, plus Lazy Load appending on scroll.)

## Application URL
https://www.saucedemo.com (pages: `/dynamic-catalog-spinner.html`, `/dynamic-catalog-lazy-load.html`)

## Test Credentials
- Username: `standard_user`
- Password: `secret_sauce`

## Acceptance Criteria

### AC1: Spinner View (happy path)
- WHEN I open the menu → Dynamic Catalog → Spinner
- THEN a loading spinner should show first and no products
- AND after a short delay the spinner should disappear and a grid of 6 products (name and price) should appear

### AC2: Lazy Load on Scroll (key behavior)
- GIVEN the Lazy Load page shows a first batch of products followed by "Loading…" placeholders
- WHEN I scroll to the end of the list
- THEN more products should appear (placeholders replaced by named, priced products)

## Business Rules
1. These views only display products; adding to the cart happens in the main catalog

## Technical Notes
- Use Playwright. Open the menu with `getByRole('button', { name: 'Open Menu' })`. Locators: `dynamic-catalog-sidebar-link`, `dynamic-catalog-spinner-link`, `dynamic-catalog-lazy-load-link`, `title`, `spinner-item-<n>`, `spinner-item-<n>-name`, `lazy-load-item-<n>-name`, `dynamic-catalog-lazy-load-sentinel` (scroll into view to load more)
- Totals aren't fixed; assert that more items appear, not an exact count. Use auto-waiting assertions, no fixed sleeps
- The agent generates and heals on Chromium only to save tokens; the target repo's CI runs the suite on all browser projects

## Definition of Done
- [ ] Acceptance criteria have test cases
- [ ] Automated test scripts created and passing on Chromium
- [ ] Test results documented
- [ ] Code committed to repository
