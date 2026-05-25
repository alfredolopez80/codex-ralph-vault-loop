# Human Playwright Patterns

This reference is for legitimate QA evidence, demos, and test review. It is not for anti-bot evasion, stealth fingerprinting, bypassing detection, or making automation look like a real user to a third-party system.

## Speed Profiles

Use these ranges for visible proof runs. Prefer `demo` unless the user requests a different pace.

| Profile  | Playwright slowMo | Typing delay |
| -------- | ----------------- | ------------ |
| `fast`   | 50-100ms          | 25-80ms      |
| `normal` | 100-250ms         | 40-120ms     |
| `demo`   | 250-500ms         | 80-180ms     |
| `slow`   | 500-900ms         | 120-260ms    |

If `HUMAN_E2E_SLOWMO_MS` is set, it overrides the profile slowMo. Keep delays short enough that assertions, not sleeps, determine correctness.

## Locator Strategy

Prefer user-facing and stable locators:

1. `page.getByRole()` with accessible names for buttons, links, headings, dialogs, inputs, and navigation.
2. `page.getByLabel()` for form controls.
3. `page.getByPlaceholder()` only when placeholder text is part of the product contract.
4. `page.getByText()` for stable user-visible copy.
5. `page.getByTestId()` for product-specific entities such as order ids, saved item rows, status badges, and generated artifacts.

Avoid CSS chains, XPath, `nth-child`, dynamic classes, and accidental text. A selector is acceptable when it describes the UI contract a user or product owner would recognize.

## Anti-Flake Strategy

- Use Playwright web-first assertions such as `await expect(locator).toBeVisible()` and `await expect(page).toHaveURL(...)`.
- Assert after each important action: route or state, visible UI, and business signal.
- Use `test.step` to make the recorded journey readable.
- Avoid `waitForTimeout()` for correctness. Use short pacing pauses only after the relevant assertion or interaction has already succeeded.
- Keep recorded proof runs at `workers=1`.
- Use isolated test data when possible.
- Limit mocks to external services or known non-core boundaries. Do not mock the product behavior being proven.
- Treat retries as diagnostic support, not a substitute for deterministic waits.

## Example Test Shape

```ts
import { expect, test } from "@playwright/test";
import { humanClick, humanType } from "./support/human";

test("user completes the primary journey", async ({ page }) => {
  await test.step("open the legitimate entry point", async () => {
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: /dashboard|welcome/i }),
    ).toBeVisible();
  });

  await test.step("perform the user-visible action", async () => {
    await humanClick(page.getByRole("button", { name: /new item/i }));
    await humanType(page.getByLabel(/name/i), "Recorded QA item");
    await humanClick(page.getByRole("button", { name: /save/i }));
  });

  await test.step("verify the business result", async () => {
    await expect(page.getByRole("status")).toContainText(/saved/i);
    await expect(page.getByTestId("item-row")).toContainText(
      "Recorded QA item",
    );
  });
});
```

## Electron Notes

For Electron apps, use Playwright `_electron` only when the app under test is actually an Electron runtime:

```ts
import { _electron as electron, expect, test } from "@playwright/test";

test("electron journey", async () => {
  const app = await electron.launch({ args: ["."] });
  const page = await app.firstWindow();

  await expect(page.getByRole("heading", { name: /home/i })).toBeVisible();

  await app.close();
});
```

Project-specific Electron launch commands vary. Inspect `package.json`, Electron main entry points, preload scripts, and existing fixtures before creating a new launcher. Do not use Electron internals to jump directly to terminal states in a happy-path E2E test.

## Recording Evidence

Recorded proof should include:

- QuickTime desktop recording when macOS permissions allow it.
- Playwright trace.
- Playwright video.
- Screenshot on failure.
- HTML report when available.
- The exact command and environment used.

When QuickTime cannot be automated because macOS blocks UI scripting or save location selection, stop and ask the user to grant Screen Recording and Accessibility permissions or manually select the output directory. Do not silently use another recorder.
