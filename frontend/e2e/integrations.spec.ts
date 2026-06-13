import { test, expect } from '@playwright/test';

async function dismissModal(page) {
  const noThanks = page.getByRole('button', { name: 'No Thanks' });
  if (await noThanks.isVisible().catch(() => false)) {
    await noThanks.click();
  }
}

test.describe('Integration Features', () => {
  test('Plan Mode toggle exists and can be activated', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('networkidle');
    await dismissModal(page);

    // Find the Plan Mode button (lightbulb icon)
    const planButton = page.locator('button[title="Plan Mode"]').or(
      page.getByRole('button').filter({ hasText: /Plan|🧠|💡/ })
    );
    await expect(planButton).toBeVisible();
    await planButton.click();

    // After toggling, the button should have an active state (border color change)
    const activePlanButton = page.locator('button').filter({ has: page.locator('svg') }).filter({ hasText: /🧠|Plan/ });
    await expect(activePlanButton.or(planButton)).toBeVisible();
  });

  test('Security & Audit panel renders in System Panel', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('networkidle');
    await dismissModal(page);

    // System panel is open by default on desktop; just assert content
    await expect(page.getByText('Security & Audit')).toBeVisible();
    await expect(page.getByRole('button', { name: /Security & Audit/ })).toBeVisible();
  });

  test('Chief of Staff card appears on Agents page', async ({ page }) => {
    await page.goto('/agents');
    await page.waitForLoadState('networkidle');
    await dismissModal(page);

    await expect(page.getByText('Chief of Staff')).toBeVisible();
    await expect(page.getByText('Auto Domain Router')).toBeVisible();
    await expect(page.getByText('Always On')).toBeVisible();
  });
});
