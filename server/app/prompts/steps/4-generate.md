Now I need to create automated test scripts using the playwright-test-generator agent.

Please review:
1. Test plan from: {PLAN_FILE} (for test scenarios and steps)
2. Exploratory testing results from the previous step (for actual element selectors and UI insights)

Using insights from the manual exploratory testing:
- Leverage the element selectors and locators that were successfully used while exploring
- Use stable element properties (this target's test-id attribute, roles, IDs) discovered
  during exploration
- Apply wait strategies and UI behaviors observed during manual testing
- Incorporate any workarounds for UI quirks discovered

Generate Playwright TypeScript automation scripts:
1. Create scripts for each test scenario from the test plan
2. Organize scripts into appropriate test suite files in: {TEST_DIR}
   (one *.spec.ts file per acceptance criterion or feature area)
3. Use the test case names and steps from the test plan
4. Use reliable selectors and strategies from exploratory testing
5. Call generator_setup_page with seedFile "{SEED}" and project "{CHROMIUM_PROJECT}"

Requirements for all scripts:
- Follow Playwright best practices
- Include proper assertions using expect()
- Use descriptive test names matching the format in the test plan
- Use robust element selectors discovered during manual testing
- Add comments for complex steps
- Use proper wait strategies based on actual application behavior (no fixed timeouts)
- Add proper test hooks (beforeEach, afterEach). Repeat the seed's setup steps in
  beforeEach; don't import the seed file
- Use relative URLs: {BASE_URL} is already the baseURL of every browser project
- Do not change playwright.config.ts. It is generated from this target's configuration
  and your edits to it are discarded

After generating the scripts, run them on Chromium only to verify they pass:
npx playwright test {TEST_DIR} --project={CHROMIUM_PROJECT}
