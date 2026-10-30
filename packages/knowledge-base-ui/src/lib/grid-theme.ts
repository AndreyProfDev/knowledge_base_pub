import { colorSchemeDark, colorSchemeLight, type Theme, themeQuartz } from 'ag-grid-community';

// Every colour a shadcn token, which `.dark` redefines; the scheme part covers the popups' unmapped shades.
export function gridThemeFor(actualTheme: 'light' | 'dark'): Theme {
  return themeQuartz.withPart(actualTheme === 'dark' ? colorSchemeDark : colorSchemeLight).withParams({
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
    browserColorScheme: actualTheme,
  });
}
