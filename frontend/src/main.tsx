import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { I18nProvider } from './lib/i18n'
import { ThemeProvider } from './lib/theme'

const Root = import.meta.env.DEV && window.location.pathname === '/__preview/talent-collaboration'
  ? (await import('./features/talentEvaluation/TalentCollaborationPreview')).default : App;

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <I18nProvider>
        <Root />
      </I18nProvider>
    </ThemeProvider>
  </StrictMode>,
)
