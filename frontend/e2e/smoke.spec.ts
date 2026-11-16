import { expect, test } from '@playwright/test';

test('WaitLess landing page shows platform branding', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/WaitLess/);
  await expect(page.getByRole('img', { name: 'WaitLess' }).first()).toBeVisible();
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Skip the wait');
});

test('restaurant storefront keeps the WaitLess link and returns to the platform', async ({ page }) => {
  await page.goto('/r/urban-bites');
  await expect(page.locator('.sf-brand__name')).toHaveText('Urban Bites');
  await page.locator('a.sf-waitless').click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Skip the wait');
});

test('admin areas render their navigation', async ({ page }) => {
  await page.goto('/restaurant-admin');
  await expect(page.locator('.ad-toolbar__title')).toHaveText('Restaurant Admin');
  await page.goto('/super-admin');
  await expect(page.locator('.ad-toolbar__title')).toHaveText('Super Admin');
});

test('unknown routes show the not-found page', async ({ page }) => {
  await page.goto('/no/such/page');
  await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
});
