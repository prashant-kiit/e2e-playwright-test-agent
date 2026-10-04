# User Story: SCRUM-208 - Navigation and Routing

## Story Title
As a user, I want to move around via tabs and recover from wrong URLs so that I never get lost.

## Story Description
The app is a single-page app with tabs, nested routes and a 404 page. (Trimmed scope: tabs plus 404 handling.)

## Application URL
https://custom-test-target-app.vercel.app (pages: `/navigation`, any unknown path)

## Test Credentials
None required.

## Acceptance Criteria

### AC1: Tabs (happy path)
- GIVEN I am on `/navigation`
- THEN the Overview tab should be selected by default (`aria-selected="true"`) with its panel visible
- WHEN I click Activity or Settings, that tab should become selected and only its panel should show
- AND switching tabs should not change the URL

### AC2: 404 Handling (key negative)
- WHEN I visit an unknown path (e.g. `/does-not-exist`)
- THEN the page should show "404 — Page not found" within the normal layout
- AND "Back to home" should return to `/`

## Business Rules
1. Navigation never reloads the whole page (client-side routing)
2. Unknown paths return HTTP 200 with the 404 page (assert on content, not status)

## Technical Notes
- Use Playwright, `page.getByTestId(...)`: `tabs`, `tab-overview|activity|settings`, `tabpanel-<id>`, `not-found-page`, `not-found-home-link`
- The agent generates and heals on Chromium only to save tokens; the target repo's CI runs the suite on all browser projects

## Definition of Done
- [ ] Acceptance criteria have test cases
- [ ] Automated test scripts created and passing on Chromium
- [ ] Test results documented
- [ ] Code committed to repository
