import { equalShares, upiLink } from './billing.service';

describe('equalShares', () => {
  it('splits to the paisa, the last payer taking the remainder', () => {
    expect(equalShares('100.00', 3)).toEqual(['33.33', '33.33', '33.34']);
    expect(equalShares(611, 2)).toEqual(['305.50', '305.50']);
    expect(equalShares('0.05', 2)).toEqual(['0.02', '0.03']);
  });

  it('treats fewer than one person as one', () => {
    expect(equalShares('50', 0)).toEqual(['50.00']);
  });
});

describe('upiLink', () => {
  it('builds a upi://pay link with a 2-decimal amount in INR', () => {
    const link = upiLink('spice@okhdfc', 'Spice Garden', '611.5', 'Bill SG-1234');
    const q = new URLSearchParams(link.split('?')[1]);
    expect(link.startsWith('upi://pay?')).toBe(true);
    expect(q.get('pa')).toBe('spice@okhdfc');
    expect(q.get('pn')).toBe('Spice Garden');
    expect(q.get('am')).toBe('611.50');
    expect(q.get('cu')).toBe('INR');
    expect(q.get('tn')).toBe('Bill SG-1234');
  });
});
