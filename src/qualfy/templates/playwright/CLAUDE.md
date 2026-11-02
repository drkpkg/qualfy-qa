# __PROJECT_NAME__ — test automation conventions

This repository holds Playwright (TypeScript) end-to-end tests. qualfy runs Claude Code here to
automate reviewed test tickets. Follow these rules for every change.

## Layout
- `tests/<area>/<ticket-key>.spec.ts` — one spec file per ticket, e.g. `tests/checkout/shop-42.spec.ts`.
- `pages/` — page objects extending `BasePage`. Add or extend a page object instead of putting
  selectors in tests.
- `fixtures/index.ts` — import `test` and `expect` from here, never from `@playwright/test`
  directly in tests.
- `specs/` — local test tickets in the qualfy YAML contract (examples and offline work).

## Writing tests
- Title every test `@<TICKET-KEY> @<CASE-ID> <case title>`, e.g. `@shop-42 @TC-1 pays with card`.
- Prefer `getByRole`, `getByLabel` and `getByTestId`; avoid CSS/XPath selectors and fixed waits.
- Set up preconditions through APIs or fixtures, not by clicking through the UI.
- Read `BASE_URL`, credentials and other inputs from environment variables. Never commit secrets.
- When the application does not match the expected result, keep the assertion and mark the test
  `test.fail()` with a comment `// app bug: <CASE-ID> <short description>`.

## Before finishing
- `npx playwright test <files>` passes (or every failure is classified).
- `npx tsc --noEmit` passes.
- Commit on the branch you were asked to use. Do not push.
