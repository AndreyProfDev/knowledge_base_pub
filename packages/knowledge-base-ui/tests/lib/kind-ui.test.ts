import type { RJSFSchema } from '@rjsf/utils';
import type { ColDef } from 'ag-grid-community';
import { describe, expect, it } from 'vitest';

import { ApiError, type MemoryItem } from '@/lib/api';
import { columnsFor, extraErrorsFor, isLongText, itemLabel, payloadFields, uiSchemaFor } from '@/lib/kind-ui';

// Shaped as the kind packages' model_json_schema() output.
const content: RJSFSchema = { type: 'string', 'x-long-text': true, title: 'Content' };
const knowledge: RJSFSchema = {
  title: 'KnowledgePayload',
  type: 'object',
  properties: {
    category: { type: 'string', enum: ['fact', 'preference'], title: 'Category' },
    content,
  },
};
const workflow: RJSFSchema = {
  type: 'object',
  properties: {
    name: { type: 'string', title: 'Name' },
    steps: { type: 'array', items: { type: 'string', title: 'Step' }, title: 'Steps' },
    tags: { type: 'array', items: { type: 'string' }, title: 'Tags' },
    aliases: { type: 'array' },
    flag: true,
  },
};
const item: MemoryItem = {
  id: '0123456789abcdef',
  kind: 'workflow',
  updated_at: '2026-10-17T09:00:00Z',
  payload: { name: 'Deploy', steps: ['build', 'ship'] },
};

function Actions(): null {
  return null;
}

const now = () => new Date('2026-10-17T11:00:00Z');
const cols = (schema: RJSFSchema, complete = true) => columnsFor(schema, { complete, actions: Actions, now });
const byId = (defs: ColDef<MemoryItem>[], id: string) => defs.find((c) => (c.colId ?? c.field) === id);
// AG Grid callbacks take a params object; these read only the fields named.
const call = (fn: unknown, params: object): unknown => (fn as (p: object) => unknown)(params);

describe('isLongText', () => {
  it('is a string marked x-long-text', () => {
    expect(isLongText({ type: 'string', 'x-long-text': true })).toBe(true);
    expect(isLongText({ type: 'string', maxLength: 4000 })).toBe(false);
    expect(isLongText({ type: 'string' })).toBe(false);
    expect(isLongText({ type: 'array', 'x-long-text': true })).toBe(false);
  });
});

describe('uiSchemaFor', () => {
  it('titles the form by kind, textareas long text, labels the submit by mode', () => {
    expect(uiSchemaFor('knowledge', knowledge, 'add')).toEqual({
      category: { 'ui:placeholder': 'Select category' },
      content: { 'ui:widget': 'textarea' },
      'ui:title': 'Knowledge',
      'ui:submitButtonOptions': { submitText: 'Add' },
    });
    expect(uiSchemaFor('knowledge', knowledge, 'edit')['ui:submitButtonOptions']).toEqual({ submitText: 'Save' });
  });

  it('numbers array items by the item title, else the property title, else the key', () => {
    const ui = uiSchemaFor('workflow', workflow, 'add');
    const items = (key: string) => (ui[key] as { items: (item: unknown, i: number) => unknown }).items;
    expect(items('steps')(undefined, 0)).toEqual({ 'ui:title': 'Step 1' });
    expect(items('tags')(undefined, 1)).toEqual({ 'ui:title': 'Tags 2' });
    expect(items('aliases')(undefined, 2)).toEqual({ 'ui:title': 'aliases 3' });
    expect(ui['name']).toBeUndefined();
  });

  it('names an untitled enum select by its key', () => {
    const schema: RJSFSchema = { type: 'object', properties: { kind: { type: 'string', enum: ['a'] } } };
    expect(uiSchemaFor('entity', schema, 'add')['kind']).toEqual({ 'ui:placeholder': 'Select kind' });
  });

  it('takes no properties for a schema without any', () => {
    expect(uiSchemaFor('entity', {}, 'add')['ui:title']).toBe('Entity');
  });
});

describe('extraErrorsFor', () => {
  it("puts each 422 msg at its loc, the payload's root for an empty one", () => {
    const error = new ApiError(422, 'Unprocessable Content', {
      detail: [
        { loc: ['body', 'content'], msg: 'over the token limit', type: 'value_error' },
        { loc: ['body'], msg: 'bad payload', type: 'value_error' },
        { loc: ['steps', 0], msg: 'too short', type: 'value_error' },
      ],
    });
    expect(extraErrorsFor(error)).toEqual({
      __errors: ['bad payload'],
      content: { __errors: ['over the token limit'] },
      steps: { 0: { __errors: ['too short'] } },
    });
  });

  it('is nothing without an error', () => {
    expect(extraErrorsFor(null)).toEqual({});
    expect(extraErrorsFor(undefined)).toEqual({});
  });

  it('puts any other failure at the root, with its status and detail', () => {
    const cases: [unknown, string][] = [
      [new ApiError(404, '', { detail: 'Unknown item k1' }), 'Save failed: 404 Unknown item k1'],
      [new ApiError(422, '', { detail: 'not a list' }), 'Save failed: 422 not a list'],
      [new ApiError(422, '', 'text'), 'Save failed: 422 text'],
      [new ApiError(422, 'Unprocessable Content', { detail: [] }), 'Save failed: 422 {"detail":[]}'],
      [new ApiError(502, 'Bad Gateway', undefined), 'Save failed: 502 Bad Gateway'],
      [new TypeError('Failed to fetch'), 'Save failed: Failed to fetch'],
      ['boom', 'Save failed: boom'],
    ];
    for (const [error, message] of cases) {
      expect(extraErrorsFor(error)).toEqual({ __errors: [message] });
    }
  });
});

describe('columnsFor', () => {
  it('shows a short id, the payload properties, Updated and Actions, in order', () => {
    const defs = cols(workflow);
    expect(defs.map((c) => c.headerName)).toEqual(['ID', 'Name', 'Steps', 'Tags', 'aliases', 'Updated', 'Actions']);
    const id = byId(defs, 'id');
    expect(call(id?.valueFormatter, { value: item.id })).toBe('01234567');
    expect(call(id?.tooltip, { value: item.id })).toBe(item.id);
    expect(id?.cellClass).toBe('font-mono text-xs text-muted-foreground');
    expect(byId(defs, 'updated_at')?.cellClass).toBe('text-muted-foreground');
    expect(byId(defs, 'actions')).toMatchObject({ cellRenderer: Actions, pinned: 'right', width: 96 });
  });

  it('reads payload values and joins arrays, which flex with a tooltip', () => {
    const defs = cols(workflow);
    const steps = byId(defs, 'steps');
    expect(call(steps?.valueGetter, { data: item })).toEqual(['build', 'ship']);
    expect(call(steps?.valueGetter, {})).toBeUndefined();
    expect(call(steps?.valueFormatter, { value: ['build', 'ship'] })).toBe('build, ship');
    expect(call(steps?.valueFormatter, { value: null })).toBe('');
    expect(steps).toMatchObject({ flex: 1, tooltip: true });
    expect(byId(defs, 'name')).toMatchObject({ width: 160 });
    expect(byId(defs, 'name')?.valueFormatter).toBeUndefined();
  });

  it('flexes long text and filters enums only once every page is in', () => {
    const complete = cols(knowledge);
    expect(byId(complete, 'content')).toMatchObject({ flex: 1, tooltip: true });
    expect(byId(complete, 'category')).toMatchObject({
      width: 140,
      filter: 'agSetColumnFilter',
      filterParams: { values: ['fact', 'preference'], suppressSorting: true },
    });
    expect(byId(cols(knowledge, false), 'category')?.filter).toBe(false);
  });

  // English under the scripts' German default locale (package.json's LC_ALL=de_DE.UTF-8, checked in tests/setup.ts).
  it('sorts Updated, shown relative to now, only once every page is in', () => {
    const updated = byId(cols(knowledge), 'updated_at');
    expect(call(updated?.valueFormatter, { value: item.updated_at })).toBe('2 hours ago');
    expect(call(updated?.tooltip, { value: item.updated_at })).toContain('2026');
    expect(call(updated?.tooltip, { value: null })).toBeUndefined();
    expect(updated).toMatchObject({ sortable: true, sortingOrder: ['desc', 'asc', null] });
    expect(byId(cols(knowledge, false), 'updated_at')?.sortable).toBe(false);
  });
});

describe('the actions column', () => {
  it('hands Tab to the cell, nothing else', () => {
    const suppress = byId(cols(knowledge), 'actions')?.suppressKeyboardEvent;
    const params = (key: string) => ({ event: new KeyboardEvent('keydown', { key }) });
    expect(call(suppress, params('Tab'))).toBe(true);
    expect(call(suppress, params('Enter'))).toBe(false);
  });
});

describe('itemLabel', () => {
  it("is the first plain string property's value", () => {
    expect(itemLabel(knowledge, { ...item, payload: { category: 'fact', content: 'Tea is green' } })).toBe(
      'Tea is green',
    );
    expect(itemLabel(workflow, item)).toBe('Deploy');
    const arrayFirst: RJSFSchema = { properties: { steps: { type: 'array' }, name: { type: 'string' } } };
    expect(itemLabel(arrayFirst, item)).toBe('Deploy');
  });

  it('is the id without such a property or value', () => {
    expect(itemLabel({ properties: { steps: { type: 'array' } } }, { ...item, payload: {} })).toBe(item.id);
    // No property named, so no payload key is read, not even "undefined".
    expect(itemLabel({ properties: {} }, { ...item, payload: { undefined: 'stray' } })).toBe(item.id);
    expect(itemLabel(knowledge, { ...item, payload: {} })).toBe(item.id);
    expect(itemLabel(knowledge, { ...item, payload: { content: '' } })).toBe(item.id);
  });
});

describe('payloadFields', () => {
  it('lists every property under its title, in schema order', () => {
    expect(payloadFields(workflow, { name: 'Deploy', steps: ['build', 'ship'], tags: [], aliases: 3 })).toEqual([
      ['Name', 'Deploy'],
      ['Steps', 'build, ship'],
      ['Tags', ''],
      ['aliases', '3'],
    ]);
  });

  it('shows a missing value as empty', () => {
    expect(payloadFields(knowledge, { category: 'fact' })).toEqual([
      ['Category', 'fact'],
      ['Content', ''],
    ]);
  });
});
