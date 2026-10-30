import { colorSchemeDark, colorSchemeLight } from 'ag-grid-community';
import { describe, expect, it } from 'vitest';

import { gridThemeFor } from '@/lib/grid-theme';

// ThemeImpl's runtime shape: the parts withPart / withParams appended, in order.
function partsOf(theme: unknown): { modeParams?: { $default?: object } }[] {
  return (theme as { parts: { modeParams?: { $default?: object } }[] }).parts;
}

describe('gridThemeFor', () => {
  it('picks the colour-scheme part for the theme', () => {
    expect(partsOf(gridThemeFor('dark'))).toContain(colorSchemeDark);
    expect(partsOf(gridThemeFor('dark'))).not.toContain(colorSchemeLight);
    expect(partsOf(gridThemeFor('light'))).toContain(colorSchemeLight);
  });

  it('maps every colour to a shadcn token and the native controls to the theme', () => {
    expect(partsOf(gridThemeFor('dark')).at(-1)?.modeParams?.$default).toEqual({
      backgroundColor: 'var(--background)',
      chromeBackgroundColor: 'var(--background)',
      foregroundColor: 'var(--foreground)',
      borderColor: 'var(--border)',
      headerBackgroundColor: 'var(--background)',
      headerTextColor: 'var(--muted-foreground)',
      headerFontWeight: 500,
      rowHoverColor: 'color-mix(in oklab, var(--muted) 50%, transparent)',
      accentColor: 'var(--ring)',
      menuBackgroundColor: 'var(--popover)',
      menuTextColor: 'var(--popover-foreground)',
      checkboxCheckedBackgroundColor: 'var(--primary)',
      statusBarLabelColor: 'var(--muted-foreground)',
      fontFamily: 'inherit',
      fontSize: 14,
      headerHeight: 40,
      rowHeight: 40,
      borderRadius: 'calc(var(--radius) - 4px)',
      wrapperBorderRadius: 'calc(var(--radius) - 2px)',
      browserColorScheme: 'dark',
    });
    expect(partsOf(gridThemeFor('light')).at(-1)?.modeParams?.$default).toMatchObject({
      browserColorScheme: 'light',
    });
  });
});
