import { createContext, type ReactNode, use, useEffect, useMemo, useState, useSyncExternalStore } from 'react';

type Theme = 'dark' | 'light' | 'system';

interface ThemeState {
  theme: Theme;
  actualTheme: 'light' | 'dark';
  setTheme: (theme: Theme) => void;
}

const DARK_QUERY = '(prefers-color-scheme: dark)';
const STORAGE_KEY = 'vite-ui-theme';

const ThemeContext = createContext<ThemeState | undefined>(undefined);

function subscribeSystem(onChange: () => void): () => void {
  const media = window.matchMedia(DARK_QUERY);
  media.addEventListener('change', onChange);
  return () => {
    media.removeEventListener('change', onChange);
  };
}

function systemTheme(): 'light' | 'dark' {
  return window.matchMedia(DARK_QUERY).matches ? 'dark' : 'light';
}

function isTheme(value: string | null): value is Theme {
  return value === 'dark' || value === 'light' || value === 'system';
}

// The OS switch moves `system` through the media query's `change` event, without a reload.
export function ThemeProvider({ children }: Readonly<{ children: ReactNode }>) {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    return isTheme(stored) ? stored : 'system';
  });
  const system = useSyncExternalStore(subscribeSystem, systemTheme);
  const actualTheme = theme === 'system' ? system : theme;

  useEffect(() => {
    const root = window.document.documentElement;
    root.classList.remove('light', 'dark');
    root.classList.add(actualTheme);
  }, [actualTheme]);

  const value = useMemo(
    () => ({
      theme,
      actualTheme,
      setTheme: (next: Theme) => {
        localStorage.setItem(STORAGE_KEY, next);
        setTheme(next);
      },
    }),
    [theme, actualTheme],
  );

  return <ThemeContext value={value}>{children}</ThemeContext>;
}

export function useTheme(): ThemeState {
  const context = use(ThemeContext);
  if (!context) throw new Error('useTheme must be used within a ThemeProvider');
  return context;
}
