import { Page, expect, test } from '@playwright/test';
import path from 'node:path';

const fixture = (name: string) => path.join(__dirname, 'fixtures', name);
const unique = () => `${Date.now()}${Math.floor(Math.random() * 1000)}`;

/** Registers a fresh restaurant through the API (faster than the form) and signs in through the UI. */
async function newOwner(page: Page): Promise<string> {
  const id = unique();
  const email = `e2e-p3-${id}@example.com`;
  const res = await page.request.post('/api/v1/public/restaurants/register', {
    data: {
      restaurant_name: `P3 Kitchen ${id}`,
      owner_name: 'Phase Three',
      email,
      mobile: `9${String(Date.now()).slice(-9)}`,
      password: 'E2e-strong-pass1',
      address: '1 Test Lane',
      city: 'Pune',
      state: 'Maharashtra',
      country: 'India',
      cuisines: ['Italian'],
      restaurant_type: 'Cafe',
      number_of_branches: 1,
    },
  });
  expect(res.status()).toBe(201);
  await page.goto('/login');
  await page.getByLabel('Email or mobile number').fill(email);
  await page.getByLabel('Password', { exact: true }).fill('E2e-strong-pass1');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/restaurant-admin$/, { timeout: 15_000 });
  return id;
}

test('owner edits profile, location and hours; checklist reflects it', async ({ page }) => {
  await newOwner(page);
  await expect(page.getByRole('heading', { name: 'Get ready to go live' })).toBeVisible();
  await page.goto('/restaurant-admin/profile');

  await page.getByLabel('Short description').fill('Wood-fired pizzas and great coffee.');
  await page.getByLabel('Website').fill('https://p3.example.com');
  await page.getByRole('button', { name: 'Save details' }).click();
  await expect(page.getByText('Saved').first()).toBeVisible();

  // Map: click to drop the pin, coordinates fill in.
  const map = page.getByRole('application', { name: /Map/ });
  await expect(map.locator('.leaflet-tile-pane')).toBeAttached();
  await map.click({ position: { x: 200, y: 150 } });
  await expect(page.getByLabel('Latitude')).not.toHaveValue('');
  await page.getByRole('button', { name: 'Save location' }).click();
  await expect(page.getByText('Saved').first()).toBeVisible();

  await page.getByRole('button', { name: 'Save hours' }).click(); // defaults 11:00–23:00 all week
  await expect(page.getByText('Saved').first()).toBeVisible();

  await page.goto('/restaurant-admin');
  const list = page.getByRole('list').filter({ hasText: 'Short description' });
  for (const label of ['Short description', 'Address pinned on the map', 'Opening hours']) {
    await expect(list.getByRole('listitem').filter({ hasText: label }).getByLabel('Done')).toBeVisible();
  }
});

test('side navigation moves between admin pages', async ({ page, isMobile }) => {
  await newOwner(page);
  if (isMobile) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('link', { name: 'Gallery' }).click();
  await expect(page).toHaveURL(/\/restaurant-admin\/gallery$/);
  await expect(page.getByRole('heading', { name: 'Gallery', level: 1 })).toBeVisible();
});

test('owner uploads logo and cover, changes colours with live preview, then resets', async ({ page }) => {
  await newOwner(page);
  await page.goto('/restaurant-admin/branding');

  await page.getByLabel('Upload logo').setInputFiles(fixture('logo.png'));
  await expect(page.getByAltText('Current logo')).toHaveAttribute('src', /\/media\/tenants\/.+\.webp$/);
  await page.getByLabel('Upload cover image').setInputFiles(fixture('cover.jpg'));
  await expect(page.getByRole('button', { name: 'Remove' })).toHaveCount(2);

  const preview = page.locator('wl-storefront-preview');
  await page.getByLabel('Primary hex value').fill('#0a7c86');
  await page.getByLabel('Primary hex value').press('Tab');
  await expect(preview).toHaveAttribute('style', /--wl-primary: #0a7c86/);
  await expect(page.getByText('unsaved changes')).toBeVisible();
  await page.getByRole('button', { name: 'Save theme' }).click();
  await expect(page.getByText('unsaved changes')).toBeHidden();

  // Survives reload (persisted on the server).
  await page.reload();
  await expect(page.getByLabel('Primary hex value')).toHaveValue('#0a7c86');

  await page.getByRole('button', { name: 'Reset to default' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Reset theme' }).click();
  await expect(page.getByLabel('Primary hex value')).toHaveValue('#b9553a');
  await expect(page.getByAltText('Current logo')).toBeVisible(); // logo is kept on reset
});

test('gallery accepts five photos, then is full; delete frees a slot', async ({ page }) => {
  await newOwner(page);
  await page.goto('/restaurant-admin/gallery');
  await expect(page.getByText('0 / 5 photos')).toBeVisible();

  for (let i = 1; i <= 5; i++) {
    await page.getByLabel('Add a photo').setInputFiles(fixture('photo.jpg'));
    await expect(page.getByText(`${i} / 5 photos`)).toBeVisible({ timeout: 15_000 });
  }
  await expect(page.getByLabel('Add a photo')).toHaveCount(0);
  await expect(page.getByText('The gallery is full')).toBeVisible();

  await page.getByLabel('Caption for photo 1').fill('Our terrace');
  await page.getByLabel('Caption for photo 1').press('Enter');
  await expect(page.getByText('Caption saved.')).toBeVisible();

  await page.getByRole('button', { name: 'Delete photo' }).first().click();
  await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click();
  await expect(page.getByText('4 / 5 photos')).toBeVisible();
  await expect(page.getByLabel('Add a photo')).toBeVisible();
});
