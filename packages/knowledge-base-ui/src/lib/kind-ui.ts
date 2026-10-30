import { type ErrorSchema, ErrorSchemaBuilder, type RJSFSchema, type UiSchema } from '@rjsf/utils';
import type { ColDef } from 'ag-grid-community';
import type { CustomCellRendererProps } from 'ag-grid-react';
import { intlFormatDistance } from 'date-fns';
import type { ComponentType } from 'react';

import { ApiError, errorMessage, type MemoryItem, validationDetails } from './api';
import { kindTitle } from './kinds';

function propertiesOf(schema: RJSFSchema): [string, RJSFSchema][] {
  return Object.entries(schema.properties ?? {}).filter((e): e is [string, RJSFSchema] => typeof e[1] === 'object');
}

// Payload models mark long text with `Field(json_schema_extra={"x-long-text": True})`.
export function isLongText(prop: RJSFSchema): boolean {
  return prop.type === 'string' && prop['x-long-text'] === true;
}

function itemTitleOf(key: string, prop: RJSFSchema): string {
  const { items } = prop;
  const itemTitle = typeof items === 'object' && !Array.isArray(items) ? items.title : undefined;
  return itemTitle ?? prop.title ?? key;
}

function fieldUiSchema(key: string, prop: RJSFSchema): UiSchema | undefined {
  if (isLongText(prop)) return { 'ui:widget': 'textarea' };
  // The theme's select is a button showing its value or placeholder, its only accessible name.
  if (prop.enum) return { 'ui:placeholder': `Select ${(prop.title ?? key).toLowerCase()}` };
  if (prop.type !== 'array') return undefined;
  const title = itemTitleOf(key, prop);
  // Without it ArrayField labels items `${fieldTitle}-${index + 1}` ("Steps-1").
  return { items: (_item: unknown, index: number) => ({ 'ui:title': `${title} ${String(index + 1)}` }) };
}

export function uiSchemaFor(kind: string, schema: RJSFSchema, mode: 'add' | 'edit'): UiSchema {
  const fields = propertiesOf(schema).flatMap(([key, prop]) => {
    const ui = fieldUiSchema(key, prop);
    return ui ? [[key, ui] as const] : [];
  });
  return {
    ...Object.fromEntries(fields),
    'ui:title': kindTitle(kind),
    'ui:submitButtonOptions': { submitText: mode === 'add' ? 'Add' : 'Save' },
  };
}

// A 422's `detail` at each field, FastAPI's leading `body` being the payload itself; any other failure at the root.
export function extraErrorsFor(error: unknown): ErrorSchema {
  if (error === null || error === undefined) return {};
  const details = error instanceof ApiError ? validationDetails(error) : undefined;
  const builder = new ErrorSchemaBuilder();
  // An empty list names no field, so it would show nothing.
  if (!details?.length) return builder.addErrors(`Save failed: ${errorMessage(error)}`).ErrorSchema;
  for (const { loc, msg } of details) {
    builder.addErrors(msg, loc[0] === 'body' ? loc.slice(1) : loc);
  }
  return builder.ErrorSchema;
}

function payloadColumn(key: string, prop: RJSFSchema, complete: boolean): ColDef<MemoryItem> {
  const col: ColDef<MemoryItem> = {
    colId: key,
    headerName: prop.title ?? key,
    valueGetter: ({ data }) => data?.payload[key],
  };
  const isArray = prop.type === 'array';
  if (isArray) col.valueFormatter = ({ value }: { value: unknown }) => displayValue(value);
  if (isArray || isLongText(prop)) Object.assign(col, { flex: 1, minWidth: 200, tooltip: true });
  else col.width = prop.enum ? 140 : 160;
  if (prop.enum) {
    // Every allowed value in schema order, not only those the loaded rows hold.
    Object.assign(col, {
      filter: complete ? 'agSetColumnFilter' : false,
      filterParams: { values: prop.enum, suppressSorting: true },
    });
  }
  return col;
}

// Sorting and filtering act on loaded rows only, so they wait for `complete` (no next page).
export function columnsFor(
  schema: RJSFSchema,
  o: { complete: boolean; actions: ComponentType<CustomCellRendererProps<MemoryItem>>; now: () => Date },
): ColDef<MemoryItem>[] {
  return [
    {
      headerName: 'ID',
      field: 'id',
      valueFormatter: ({ value }: { value: string }) => value.slice(0, 8),
      cellClass: 'font-mono text-xs text-muted-foreground',
      tooltip: ({ value }: { value?: string | null }) => value,
      width: 110,
    },
    ...propertiesOf(schema).map(([key, prop]) => payloadColumn(key, prop, o.complete)),
    {
      headerName: 'Updated',
      field: 'updated_at',
      valueFormatter: ({ value }: { value: string }) => intlFormatDistance(value, o.now(), { locale: 'en' }),
      cellClass: 'text-muted-foreground',
      tooltip: ({ value }: { value?: string | null }) => (value ? new Date(value).toLocaleString() : undefined),
      sortable: o.complete,
      // An omitted `sort` keeps the grid's applied one.
      ...(o.complete ? {} : { sort: null }),
      sortingOrder: ['desc', 'asc', null],
      width: 140,
    },
    {
      headerName: 'Actions',
      colId: 'actions',
      cellRenderer: o.actions,
      pinned: 'right',
      width: 96,
      // Tab and Shift+Tab move between the cell and its menu trigger.
      suppressKeyboardEvent: ({ event }) => event.key === 'Tab',
    },
  ];
}

function displayValue(value: unknown): string {
  if (Array.isArray(value)) return value.join(', ');
  if (typeof value === 'string') return value;
  return value === undefined || value === null ? '' : JSON.stringify(value);
}

// A search hit's payload as [title, text] pairs, in schema order.
export function payloadFields(schema: RJSFSchema, payload: Record<string, unknown>): [string, string][] {
  return propertiesOf(schema).map(([key, prop]) => [prop.title ?? key, displayValue(payload[key])]);
}

// The first plain string property is each kind's key text: `content`, `name`, `name`; else the id.
export function itemLabel(schema: RJSFSchema, item: MemoryItem): string {
  const key = propertiesOf(schema).find(([, prop]) => prop.type === 'string' && !prop.enum)?.[0];
  const value = key === undefined ? undefined : item.payload[key];
  return typeof value === 'string' && value !== '' ? value : item.id;
}
