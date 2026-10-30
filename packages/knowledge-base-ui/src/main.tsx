import './index.css';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from '@tanstack/react-router';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { createApi } from './lib/api';
import { createAppRouter } from './router';

const rootElement = document.getElementById('root');
if (!rootElement) throw new Error('index.html has no #root');

const queryClient = new QueryClient();
const router = createAppRouter({ queryClient, ...createApi() });

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
