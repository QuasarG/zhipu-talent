import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { I18nProvider } from './lib/i18n'
import { ThemeProvider } from './lib/theme'

const Prototype = import.meta.env.DEV && window.location.pathname === '/prototype/agent-space'
  ? lazy(() => import('./pages/AgentSpacePrototype')) : null;

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <I18nProvider>
        {Prototype ? <Suspense fallback={<p>正在加载交互原型…</p>}><Prototype /></Suspense> : <App />}
      </I18nProvider>
    </ThemeProvider>
  </StrictMode>,
)
