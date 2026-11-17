import { Page, expect, test } from '@playwright/test';

/**
 * PRD acceptance tests 4, 5 and 6 against the demo restaurants created by global-setup:
 *   Urban Bites (teal theme, Pune, pizzas)  ·  Restaurant Remelle (default theme, Mumbai, salmon)
 */

const primary = (page: Page) =>
  page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--wl-primary').trim());

async function openMenu(page: Page, isMobile: boolean, label: string): Promise<void> {
  if (isMobile) await page.getByRole('button', { name: 'Toggle navigation' }).click();
  await page.getByRole('navigation', { name: 'Restaurant' }).getByRole('link', { name: label }).click();
}

test('discovery finds published restaurants and filters by city', async ({ page }) => {
  await page.goto('/restaurants');
  await expect(page.getByRole('link', { name: /Urban Bites/ }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Restaurant Remelle/ }).first()).toBeVisible();

  await page.getByLabel('City').selectOption('Pune');
  await expect(page).toHaveURL(/city=Pune/);
  await expect(page.getByRole('link', { name: /Urban Bites/ }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /Restaurant Remelle/ })).toHaveCount(0);

  await page.getByRole('link', { name: /Urban Bites/ }).first().click();
  await expect(page).toHaveURL(/\/r\/urban-bites$/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Urban Bites');
});

test('switching restaurants A → B → A never shows the other restaurant’s data', async ({ page, isMobile }) => {
  // A: Urban Bites
  await page.goto('/r/urban-bites');
  await expect(page.locator('.sf-brand__name')).toHaveText('Urban Bites');
  await expect(page.locator('.sf-brand__img')).toBeVisible(); // its own logo
  expect(await primary(page)).toBe('#0a7c86');
  await openMenu(page, isMobile, 'Menu');
  await expect(page.getByRole('heading', { name: 'Pizza Margherita' })).toBeVisible();
  await expect(page.getByText('Grilled Salmon')).toHaveCount(0);

  // Back to WaitLess (client-side navigation, same app instance)
  await page.locator('a.sf-waitless').click();
  await expect(page).toHaveURL(/\/$/);
  expect(await primary(page)).toBe('#b9553a'); // WaitLess branding restored

  // B: Restaurant Remelle via search
  await page.getByLabel('Search restaurants').fill('Remelle');
  await page.getByRole('button', { name: 'Search' }).click();
  await page.getByRole('link', { name: /Restaurant Remelle/ }).first().click();
  await expect(page.locator('.sf-brand__name')).toHaveText('Restaurant Remelle');
  await openMenu(page, isMobile, 'Menu');
  await expect(page.getByRole('heading', { name: 'Grilled Salmon' })).toBeVisible();
  await expect(page.getByText('Pizza Margherita')).toHaveCount(0);
  await openMenu(page, isMobile, 'Contact');
  await expect(page.getByText(/Marine Drive/).first()).toBeVisible();
  await expect(page.getByText(/Koregaon Park/)).toHaveCount(0);

  // A again: everything is Urban Bites once more
  await page.goto('/r/urban-bites/contact');
  await expect(page.getByText(/Koregaon Park/).first()).toBeVisible();
  await expect(page.getByText(/Marine Drive/)).toHaveCount(0);
  expect(await primary(page)).toBe('#0a7c86');
});

test('gallery opens a lightbox with next / previous and closes with Escape', async ({ page }) => {
  await page.goto('/r/urban-bites/gallery');
  const photos = page.getByRole('button', { name: /Enlarge photo/ });
  await expect(photos).toHaveCount(3);
  await photos.first().click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toHaveAttribute('aria-label', 'Photo 1 of 3');
  await page.keyboard.press('ArrowRight');
  await expect(dialog).toHaveAttribute('aria-label', 'Photo 2 of 3');
  await dialog.getByRole('button', { name: 'Previous photo' }).click();
  await expect(dialog).toHaveAttribute('aria-label', 'Photo 1 of 3');
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
});

test('menu filters: meal type, veg only and search', async ({ page }) => {
  await page.goto('/r/remelle/menu');
  await expect(page.getByRole('heading', { name: 'Grilled Salmon' })).toBeVisible();
  await page.getByLabel('Veg only').check();
  await expect(page.getByRole('heading', { name: 'Grilled Salmon' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Truffle Mushroom Pasta' })).toBeVisible();
  await page.getByLabel('Veg only').uncheck();
  await page.getByLabel('Search dishes').fill('risotto');
  await expect(page.getByRole('heading', { name: 'Seafood Risotto' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Grilled Salmon' })).toHaveCount(0);
});

test('unknown restaurant shows a friendly message', async ({ page }) => {
  await page.goto('/r/no-such-restaurant-here');
  await expect(page.getByRole('heading', { name: "This restaurant isn't on WaitLess yet" })).toBeVisible();
});

test('landing page contact form', async ({ page }) => {
  await page.goto('/');
  const form = page.locator('form.contact__form');
  await form.getByLabel('Name').fill('E2E Visitor');
  await form.getByLabel('Email').fill('e2e-visitor@example.com');
  await form.getByLabel('Message').fill('Hello WaitLess, this is an automated test message.');
  await form.getByRole('button', { name: 'Send message' }).click();
  await expect(page.getByText('The WaitLess team will get back to you')).toBeVisible();
});

test('owner builds a menu and previews the unpublished storefront', async ({ page }) => {
  const id = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const email = `e2e-p4-${id}@example.com`;
  const res = await page.request.post('/api/v1/public/restaurants/register', {
    data: {
      restaurant_name: `P4 Diner ${id}`,
      owner_name: 'Phase Four',
      email,
      mobile: `9${String(Date.now()).slice(-9)}`,
      password: 'E2e-strong-pass1',
      address: '1 Test Lane',
      city: 'Pune',
      state: 'Maharashtra',
      country: 'India',
      cuisines: ['Italian'],
      restaurant_type: 'Cafe',
    },
  });
  expect(res.status()).toBe(201);
  const slug = (await res.json()).tenant.slug as string;

  await page.goto('/login');
  await page.getByLabel('Email or mobile number').fill(email);
  await page.getByLabel('Password', { exact: true }).fill('E2e-strong-pass1');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/restaurant-admin$/, { timeout: 15_000 });

  await page.goto('/restaurant-admin/menu');
  await page.getByRole('button', { name: /^Starters/ }).click();
  await page.getByRole('button', { name: 'Add dish' }).first().click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Name').fill('Paneer Tikka');
  await dialog.getByLabel('Price (₹)').fill('320');
  await dialog.getByRole('button', { name: 'Add dish' }).click();
  await expect(page.getByText('Dish added.')).toBeVisible();
  await expect(page.locator('.item').filter({ hasText: 'Paneer Tikka' })).toBeVisible();

  // Not published yet → guests get "not found", the owner gets a preview.
  await page.goto(`/r/${slug}/menu`);
  await expect(page.getByText('Preview — guests cannot see this storefront')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Paneer Tikka' })).toBeVisible();
});
