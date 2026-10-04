# User Story: SCRUM-208 - Site Navigation and Routing

## Story Title
As a user, I want to move around the app through the menu, tabs, links and breadcrumbs, and to recover from wrong URLs, so that I never get lost.

## Story Description
The app is a single-page application with a persistent navigation bar. The Navigation page demonstrates tabs that don't change the URL, nested routes with a URL parameter and breadcrumbs, programmatic navigation (go to a page, go back) and an external link that opens in a new tab. Unknown URLs show a 404 page.

## Application URL
https://custom-test-target-app.vercel.app (pages: `/`, `/navigation`, `/navigation/items/:itemId`, any unknown path)

## Test Credentials
None required. These pages are public.

## Acceptance Criteria

### AC1: Global Navigation Bar and Home Page
- Every page should show the navigation bar with the brand link "PW Practice Target" and links Home, Forms, Buttons, Modals, Dropdowns, Table, Dynamic Content, Navigation, Dashboard and Log in
- Clicking each link should load the matching page and URL, and mark that link as active
- The Home page should show eight feature cards (Forms, Buttons, Modals, Dropdowns, Table, Dynamic Content, Navigation, Auth), each linking to its page
- The Home page "App status" badge should show "checking…" and then "online"

### AC2: Tabs
- The Overview tab should be selected by default (`aria-selected="true"`) with its panel visible
- Clicking Activity or Settings should select that tab and show only its panel
- Switching tabs should not change the URL

### AC3: Nested Routes and Breadcrumbs
- The items list should link Alpha, Beta and Gamma to `/navigation/items/alpha|beta|gamma`
- The detail page should show the heading "Item: <Name>", the item id in code, and the breadcrumbs "Navigation / Items / <Name>"
- The breadcrumb links and "Back to Navigation" should return to `/navigation`
- Opening a detail URL directly (deep link) should work
- An unknown item id (e.g. `/navigation/items/xyz`) should still render, using the raw id as the name

### AC4: Programmatic Navigation and History
- "Go to Table page" should navigate to `/table`
- "Go back" should return to the previous page in history
- The browser Back and Forward buttons should move between visited routes correctly
- "Open Playwright docs (new tab)" should open `https://playwright.dev` in a new tab and leave the current tab on `/navigation`

### AC5: 404 Handling
- Visiting an unknown path (e.g. `/does-not-exist`) should show "404 — Page not found" inside the normal layout
- "Back to home" should return to `/`

## Business Rules
1. Navigation never reloads the whole page (client-side routing)
2. Every route can be opened directly by URL
3. External links open in a new tab and don't replace the app

## Technical Notes
- Use Playwright for test automation
- Test across Chrome, Firefox, Safari and a mobile viewport
- Test IDs: `brand-link`, `nav-link-home|forms|buttons|modals|dropdowns|table|dynamic-content|navigation|dashboard|login`, `home-page`, `home-card-<title>`, `status-badge`, `tabs`, `tab-overview|activity|settings`, `tabpanel-<id>`, `navigation-items-list`, `navigation-item-link-<id>`, `navigation-detail-page`, `navigation-detail-title`, `navigation-detail-id`, `breadcrumbs`, `breadcrumb-current`, `back-to-navigation-link`, `goto-table-button`, `go-back-button`, `external-link`, `not-found-page`, `not-found-home-link`
- The active nav link gets the class `active`. Assert it with `toHaveClass(/active/)`
- For the external link, use `context.waitForEvent('page')`. Assert the new tab's URL, not its content, so the suite doesn't depend on playwright.dev being up
- Unknown paths return HTTP 200 (the SPA serves the 404 page). Assert on the page content, not the status code
- On the `practice-target-mobile-chrome` viewport the nav bar may wrap. Keep link assertions visibility-based

## Definition of Done
- [ ] All acceptance criteria have test cases
- [ ] Manual exploratory testing completed
- [ ] Automated test scripts created and passing
- [ ] Test results documented
- [ ] Bugs logged for any failures
- [ ] Code committed to repository
