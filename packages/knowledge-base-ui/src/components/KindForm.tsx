import type { IChangeEvent } from '@rjsf/core';
import Form from '@rjsf/shadcn';
import { getUiOptions, type RJSFSchema, type TitleFieldProps } from '@rjsf/utils';
import validator from '@rjsf/validator-ajv8';
import { useNavigate, useRouteContext } from '@tanstack/react-router';
import { useMemo } from 'react';

import { usePending } from '@/components/PendingRequests';
import type { MemoryItem, WriteAccepted } from '@/lib/api';
import { extraErrorsFor, uiSchemaFor } from '@/lib/kind-ui';
import { isEditLocked, writtenIds } from '@/lib/pending';

type Payload = Record<string, unknown>;

// The theme's TitleField is an h5, which skips levels under the page's h1 (axe heading-order).
function TitleField({ id, title, uiSchema }: Readonly<TitleFieldProps>) {
  return (
    <h2 id={id} className="my-1 border-b pb-2 font-medium">
      {getUiOptions(uiSchema).title ?? title}
    </h2>
  );
}

const templates = { TitleFieldTemplate: TitleField };

// Add without `item`, edit with it. A queued write is tracked and the list shown; a 422 lands in the form.
export function KindForm({ kind, schema, item }: Readonly<{ kind: string; schema: RJSFSchema; item?: MemoryItem }>) {
  const { $api } = useRouteContext({ from: '__root__' });
  const { pending, track } = usePending();
  const navigate = useNavigate();
  const onSuccess = (accepted: WriteAccepted) => {
    // A key-changing edit writes its new key's row too, which may already exist.
    track({ requestId: accepted.request_id, kind, itemIds: writtenIds(item?.id, accepted.item_id), action: 'save' });
  };
  const add = $api.useMutation('post', '/memory/{kind}', { onSuccess });
  const save = $api.useMutation('put', '/memory/{kind}/{item_id}', { onSuccess });
  // Per call, so it is skipped once the form has unmounted (the user went elsewhere meanwhile).
  const toList = {
    onSuccess: () => {
      void navigate({ to: '/$kind', params: { kind } });
    },
  };
  const uiSchema = useMemo(() => uiSchemaFor(kind, schema, item ? 'edit' : 'add'), [kind, schema, item]);
  const locked = item !== undefined && isEditLocked(pending, item.id);
  const error = (item ? save : add).error;
  const extraErrors = useMemo(() => extraErrorsFor(error), [error]);

  const submit = ({ formData = {} }: IChangeEvent<Payload>) => {
    if (item) save.mutate({ params: { path: { kind, item_id: item.id } }, body: formData }, toList);
    else add.mutate({ params: { path: { kind } }, body: formData }, toList);
  };

  return (
    <Form
      schema={schema}
      uiSchema={uiSchema}
      templates={templates}
      validator={validator}
      formData={item?.payload}
      extraErrors={extraErrors}
      disabled={locked || add.isPending || save.isPending}
      onSubmit={submit}
    />
  );
}
