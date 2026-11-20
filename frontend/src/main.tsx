import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { App } from './App'
import { AssistantProvider } from './components/AssistantProvider'
import { ViewerProvider } from './components/ViewerProvider'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Figures only change when a sync runs or someone acts on an issue, and
      // both of those refetch explicitly. No need to refetch on every focus.
      staleTime: 60_000,
      refetchOnWindowFocus: false,
      // The API explains its errors, so retrying a 404 or 409 only delays the message.
      retry: false,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ViewerProvider>
        <BrowserRouter>
          <AssistantProvider>
            <App />
          </AssistantProvider>
        </BrowserRouter>
      </ViewerProvider>
    </QueryClientProvider>
  </StrictMode>,
)
