import { expect, test } from '@playwright/test';

const unique = () => `${Date.now()}${Math.floor(Math.random() * 1000)}`;
const mobile = () => `9${Math.floor(100000000 + Math.random() * 899999999)}`;

test('restaurant owner registers, lands on the dashboard, signs out and back in', async ({ page }) => {
  const id = unique();
  const email = `e2e-owner-${id}@example.com`;
  const password = 'E2e-strong-pass1';

  await page.goto('/register-restaurant');
  await page.getByLabel('Restaurant name').fill(`E2E Bistro ${id}`);
  await page.getByLabel('Restaurant type').click();
  await page.getByRole('option', { name: 'Cafe', exact: true }).click(); // not the "Cafe & Bakery" cuisine chip
  await page.getByRole('option', { name: 'Italian', exact: true }).click();
  await page.getByLabel('Owner name').fill('E2E Owner');
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByLabel('Mobile number', { exact: true }).fill(mobile());
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByLabel('Street address').fill('1 Test Lane');
  await page.getByLabel('City', { exact: true }).fill('Pune');
  await page.getByLabel('State', { exact: true }).fill('Maharashtra');
  await expect(page.getByLabel('Web address')).toHaveValue(new RegExp(`e2e-bistro-${id}`));
  await page.getByRole('button', { name: 'Register restaurant' }).click();

  // Registration + automatic sign-in hash the password twice (Argon2), allow extra time.
  await expect(page).toHaveURL(/\/restaurant-admin$/, { timeout: 15_000 });
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(`E2E Bistro ${id}`);
  await expect(page.getByText('Awaiting WaitLess approval')).toBeVisible();
  await expect(page.getByText('Professional')).toBeVisible();

  // Session survives a full reload (refresh cookie -> new access token).
  await page.reload();
  await expect(page.getByText('Awaiting WaitLess approval')).toBeVisible();

  await page.getByRole('button', { name: /Account menu/ }).click();
  await page.getByRole('menuitem', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/\/$/);

  await page.goto('/restaurant-admin');
  await expect(page).toHaveURL(/\/login\?returnUrl=%2Frestaurant-admin/);
  await page.getByLabel('Email or mobile number').fill(email);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/restaurant-admin$/);
});

test('wrong password shows a clear error', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel('Email or mobile number').fill(`nobody-${unique()}@example.com`);
  await page.getByLabel('Password', { exact: true }).fill('wrong-password');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('alert')).toContainText('Invalid email/mobile or password');
});

test('guest signs in with a mobile one-time code', async ({ page }) => {
  await page.goto('/login');
  await page.getByRole('tab', { name: 'Guest (mobile)' }).click();
  await page.getByLabel('Mobile number', { exact: true }).fill(mobile());
  await page.getByRole('button', { name: 'Send code' }).click();

  const note = page.getByRole('note');
  await expect(note).toContainText('Your code is');
  const code = (await note.locator('b').textContent())!.trim();
  await page.getByLabel('6-digit code').fill(code);
  await page.getByLabel('Your name (first time only)').fill('E2E Guest');
  await page.getByRole('button', { name: /Verify/ }).click();

  await expect(page).toHaveURL(/\/customer$/);
  await page.goto('/super-admin/restaurants');
  await expect(page).toHaveURL(/\/customer$/); // not a super admin
});
