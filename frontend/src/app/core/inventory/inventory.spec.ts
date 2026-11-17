import { qty, recipeUnits, toCsv } from './inventory.service';

describe('inventory helpers', () => {
  it('shows quantities without trailing zeros', () => {
    expect(qty('4.500')).toBe('4.5');
    expect(qty('50.000')).toBe('50');
    expect(qty('-0.300')).toBe('-0.3');
    expect(qty(0.1 + 0.2)).toBe('0.3');
  });

  it('offers the small unit for recipes of items stocked in kg / l', () => {
    expect(recipeUnits('kg')).toEqual(['g', 'kg']);
    expect(recipeUnits('ml')).toEqual(['ml', 'l']);
    expect(recipeUnits('pcs')).toEqual(['pcs']);
  });

  it('builds Excel-friendly CSV with quoting', () => {
    const csv = toCsv(['Item', 'Reason'], [['Paneer', 'Spoiled, "bad" batch'], ['Milk', null]]);
    expect(csv.startsWith('﻿Item,Reason\r\n')).toBe(true);
    expect(csv).toContain('Paneer,"Spoiled, ""bad"" batch"\r\n');
    expect(csv).toContain('Milk,\r\n');
  });
});
