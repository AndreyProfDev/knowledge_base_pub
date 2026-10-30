import { describe, expect, it } from 'vitest';

import { gridModules, licenceProps } from '@/lib/grid-modules';

describe('gridModules', () => {
  it('registers the seven modules the list needs, not an all-in bundle', () => {
    expect(gridModules.map((m) => m.moduleName)).toEqual([
      'ClientSideRowModel',
      'Tooltip',
      'CellStyle',
      'RenderApi',
      'ContextMenu',
      'SetFilter',
      'StatusBar',
    ]);
  });
});

describe('licenceProps', () => {
  it('passes no licenseKey for an empty or missing key', () => {
    expect(licenceProps('')).toEqual({});
    expect(licenceProps(undefined)).toEqual({});
  });

  it('passes a set key through', () => {
    expect(licenceProps('key-123')).toEqual({ licenseKey: 'key-123' });
  });
});
