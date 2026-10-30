import { describe, expect, it } from 'vitest';

import { isTrialBanner } from '@/lib/ag-grid-banner';

const STARS = '*'.repeat(124);

describe('isTrialBanner', () => {
  it('is each line of the no-key trial banner, alone or joined', () => {
    const lines = [
      STARS,
      `${'*'.repeat(49)} AG Grid Enterprise License ${'*'.repeat(48)}`,
      `${'*'.repeat(50)} License Key Not Found ${'*'.repeat(51)}`,
      `* All AG Grid Enterprise features are unlocked for trial.${' '.repeat(66)}*`,
      `* If you want to hide the watermark please email info@ag-grid.com for a trial license key.${' '.repeat(33)}*`,
    ];
    for (const line of lines) expect(isTrialBanner(line)).toBe(true);
    expect(isTrialBanner(`\n${lines.join('\n')}\n`)).toBe(true);
  });

  it("is not an invalid or expired key's banner, nor any other starred error", () => {
    expect(isTrialBanner(`${STARS}\n${'*'.repeat(50)} Invalid License ${'*'.repeat(57)}`)).toBe(false);
    expect(isTrialBanner('*foo')).toBe(false);
    expect(isTrialBanner('* Your license key has expired. *')).toBe(false);
  });

  it('is not a banner line with anything before or after it', () => {
    const lines = [
      '* AG Grid Enterprise License *',
      '* License Key Not Found *',
      '* All AG Grid Enterprise features are unlocked for trial. *',
      '* If you want to hide the watermark please email info@ag-grid.com for a trial license key. *',
    ];
    for (const line of lines) {
      expect(isTrialBanner(line)).toBe(true);
      expect(isTrialBanner(`x${line}`)).toBe(false);
      expect(isTrialBanner(`${line}x`)).toBe(false);
    }
  });
});
