import { equalShares } from './billing.service';

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
