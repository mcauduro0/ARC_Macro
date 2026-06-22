// ARC 2.0 Mesa UI — e2e smoke (Playwright). Resilient to the bridge being offline: it asserts the shell
// chrome, the prime-directive honesty messaging, and that the autonomy nav routes render — the things that
// must hold whether or not the FastAPI bridge is serving live state.
//
// Enable locally: `pnpm add -D @playwright/test && pnpm exec playwright install chromium && pnpm test:e2e`
import { expect, test } from "@playwright/test";

test.describe("ARC 2.0 shell", () => {
  test("renders the Mesa top bar and autonomy nav", async ({ page }) => {
    await page.goto("/");
    // brand chrome (always present, no data needed)
    await expect(page.getByText("ARC", { exact: true })).toBeVisible();
    await expect(page.getByText("Risk OS")).toBeVisible();
    // the 7 autonomy areas
    for (const area of ["Command", "Co-pilot", "Holdout", "Risk", "Macro", "Research", "Ledger"]) {
      await expect(page.getByRole("link", { name: area })).toBeVisible();
    }
  });

  test("Command surfaces the prime directive (or an honest offline panel)", async ({ page }) => {
    await page.goto("/");
    const promoted = page.getByText(/NOTHING PROMOTED/i);
    const offline = page.getByText(/bridge offline/i);
    // exactly one of: live honesty banner, or the bridge-offline panel — never a fabricated track record
    await expect(promoted.or(offline).first()).toBeVisible();
  });

  test("nav routes to Holdout and Macro", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "Holdout" }).click();
    await expect(page).toHaveURL(/\/holdout$/);
    await page.getByRole("link", { name: "Macro" }).click();
    await expect(page).toHaveURL(/\/macro$/);
  });
});
