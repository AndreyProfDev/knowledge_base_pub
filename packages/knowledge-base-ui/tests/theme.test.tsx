import { act, renderHook, screen } from '@testing-library/react';
import { toast } from 'sonner';
import { describe, expect, it } from 'vitest';

import { useTheme } from '@/components/theme-provider';

import { fakeApi, kinds, page } from './fake-api';
import { setSystemDark } from './media';
import { renderRoute } from './render-route';

const api = () => fakeApi({ 'GET /kinds': () => Response.json(kinds), 'GET /memory/knowledge': () => page([]) });

describe('theme', () => {
  it('starts from the system scheme, light under jsdom', async () => {
    await renderRoute('/knowledge', api());

    await screen.findByRole('button', { name: 'Toggle theme' });
    expect(document.documentElement.className).toBe('light');
  });

  it('switches to dark from the toggle, persists it and themes the toasts', async () => {
    const { user } = await renderRoute('/knowledge', api());

    await user.click(await screen.findByRole('button', { name: 'Toggle theme' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Dark' }));
    act(() => {
      toast('Hello');
    });

    expect(document.documentElement.className).toBe('dark');
    expect(localStorage.getItem('vite-ui-theme')).toBe('dark');
    const toaster = (await screen.findByText('Hello')).closest('[data-sonner-theme]');
    expect(toaster?.getAttribute('data-sonner-theme')).toBe('dark');
  });

  it('follows an OS scheme change under System, without a reload', async () => {
    localStorage.setItem('vite-ui-theme', 'dark');
    const { user } = await renderRoute('/knowledge', api());
    await user.click(await screen.findByRole('button', { name: 'Toggle theme' }));
    await user.click(await screen.findByRole('menuitem', { name: 'System' }));
    expect(document.documentElement.className).toBe('light');

    act(() => {
      setSystemDark(true);
    });
    expect(document.documentElement.className).toBe('dark');
  });

  it('reads a stored theme', async () => {
    localStorage.setItem('vite-ui-theme', 'dark');
    await renderRoute('/knowledge', api());

    await screen.findByRole('button', { name: 'Toggle theme' });
    expect(document.documentElement.className).toBe('dark');
  });

  it('throws without a provider', () => {
    expect(() => renderHook(() => useTheme())).toThrow('useTheme must be used within a ThemeProvider');
  });
});
