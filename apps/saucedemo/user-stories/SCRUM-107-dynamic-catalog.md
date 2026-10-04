# User Story: SCRUM-107 - Dynamic Catalog Views

## Story Title
As a customer, I want alternative catalog views that load products as I need them so that browsing stays fast and engaging.

## Story Description
The menu's "Dynamic Catalog" submenu opens three views of the product catalog, each loading products in a different way: Lazy Load (more products appear as I scroll), Spinner (a spinner shows while products load) and Slider (one product at a time, rotating automatically, with dots to jump to a product).

## Application URL
https://www.saucedemo.com (pages: `/dynamic-catalog-lazy-load.html`, `/dynamic-catalog-spinner.html`, `/dynamic-catalog-slider.html`)

## Test Credentials
- Username: `standard_user`
- Password: `secret_sauce`

## Acceptance Criteria

### AC1: Submenu
- WHEN I open the menu and click "Dynamic Catalog"
- THEN a submenu with Lazy Load, Spinner and Slider should appear
- AND each item should open its page, titled "Dynamic Catalog - Lazy Load", "Dynamic Catalog - Spinner" and "Dynamic Catalog - Slider"

### AC2: Lazy Load
- The page should first show a batch of products (each with name and price), followed by "Loading…" placeholders
- Scrolling to the end of the list should replace placeholders with more products and add new placeholders
- Every loaded product should have a name and a price

### AC3: Spinner
- On opening the page a loading spinner should be visible and no products should be listed
- After a short delay (about 2 seconds) the spinner should disappear and a grid of 6 products with names and prices should appear

### AC4: Slider
- The page should show one product (name and price) and 6 dots, one per product, with the current dot marked `aria-current="true"`
- The slider should move to the next product on its own after a few seconds
- Clicking a dot should show that product and mark its dot as current
- Each dot should have an accessible name "Show <product name>"

### AC5: Access Control
- Opening any Dynamic Catalog page while logged out should send me to the login page

## Business Rules
1. The Dynamic Catalog pages only display products. Adding to the cart happens in the main catalog
2. All three views use the same product names and prices as the main catalog

## Technical Notes
- Use Playwright for test automation
- Test across Chrome, Firefox, Safari and a mobile viewport
- Open the menu with `getByRole('button', { name: 'Open Menu' })`. Locators: `dynamic-catalog-sidebar-link`, `dynamic-catalog-submenu`, `dynamic-catalog-lazy-load-link`, `dynamic-catalog-spinner-link`, `dynamic-catalog-slider-link`, `title`
- Lazy Load: `dynamic-catalog-lazy-load-container`, `lazy-load-item-<n>`, `lazy-load-item-<n>-name`, `lazy-load-item-<n>-price`, `lazy-load-item-<n>-placeholder`, `dynamic-catalog-lazy-load-sentinel` (scroll it into view to load more). The total number of items is not specified; assert that more items appear, not an exact total
- Spinner: `dynamic-catalog-spinner`, `dynamic-catalog-spinner-grid`, `spinner-item-<n>`, `spinner-item-<n>-name`, `spinner-item-<n>-price`
- Slider: `dynamic-catalog-slider-container`, `dynamic-catalog-slider-item`, `dynamic-catalog-slider-item-name`, `dynamic-catalog-slider-item-price`, `dynamic-catalog-slider-dots`, `dynamic-catalog-slider-dot-<n>`
- The slider rotates on a timer. Assert with auto-waiting checks (e.g. wait for the name to change) rather than an exact timing, and check a dot click right after clicking, before the next rotation
- Product names in Lazy Load can include a size suffix (e.g. "Sauce Labs Fleece Jacket (XS)"). Compare base names when checking against the main catalog

## Definition of Done
- [ ] All acceptance criteria have test cases
- [ ] Manual exploratory testing completed
- [ ] Automated test scripts created and passing
- [ ] Test results documented
- [ ] Bugs logged for any failures
- [ ] Code committed to repository
