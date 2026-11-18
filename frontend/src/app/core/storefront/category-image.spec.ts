import { categoryImage } from './storefront.models';

describe('categoryImage (default category photos)', () => {
  const img = (name: string) => categoryImage(name, null);

  it("prefers the owner's own photo", () => {
    expect(categoryImage('Starters', '/media/x.webp')).toBe('/media/x.webp');
  });

  it('picks the template photo by kind of category', () => {
    expect(img('Starters')).toBe('menu-categories/starters.jpg');
    expect(img('Main Course')).toBe('menu-categories/main.jpg');
    expect(img('Desserts')).toBe('menu-categories/desserts.jpg');
    expect(img('Soup Bowls')).toBe('menu-categories/soups.jpg');
    expect(img('Wood-fired Pizzas')).toBe('menu-categories/pizza.jpg');
  });

  it('keeps soft drinks and the bar apart', () => {
    expect(img('Mocktails')).toBe('menu-categories/beverages.jpg');
    expect(img('Non-Alcoholic')).toBe('menu-categories/beverages.jpg');
    expect(img('Alcoholic')).toBe('menu-categories/bar.jpg');
    expect(img('Cocktails')).toBe('menu-categories/bar.jpg');
    expect(img('Barbecue Platters')).toBe('menu-categories/main.jpg'); // "bar" only as a word
  });
});
