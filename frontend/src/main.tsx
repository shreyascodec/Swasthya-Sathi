import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { AvatarSmoke } from './avatar/AvatarSmoke'

// Phase-A verification: http://localhost:5173/#avatar-smoke
const smoke = typeof window !== 'undefined' && window.location.hash === '#avatar-smoke'
const Root = smoke ? AvatarSmoke : App

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
