import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AuthProvider } from 'react-oidc-context'
import './index.css'
import App from './App.jsx'
import { oidcConfig } from './auth.config.js'
import { initRippleEffect } from './rippleEffect.js'
import { ThemeProvider } from './ThemeContext.jsx'

import { ThemeProvider } from './ThemeContext.jsx'

// DIAGNOSTIC INTERCEPTOR
const _origLog = console.log;
const _origWarn = console.warn;
function writeLog(args, color) {
  const div = document.getElementById('diag-logs');
  if (div) {
    const span = document.createElement('span');
    span.style.color = color;
    span.innerText = Array.from(args).map(a => typeof a === 'object' ? JSON.stringify(a) : a).join(' ') + '\n';
    div.appendChild(span);
    div.scrollTop = div.scrollHeight;
  }
}
console.log = function(...args) {
  _origLog.apply(console, args);
  if (args.some(a => typeof a === 'string' && a.includes('[DIAG]'))) writeLog(args, 'lime');
};
console.warn = function(...args) {
  _origWarn.apply(console, args);
  if (args.some(a => typeof a === 'string' && a.includes('[DIAG]'))) writeLog(args, 'orange');
};

initRippleEffect();

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ThemeProvider>
      <AuthProvider {...oidcConfig}>
        <App />
      </AuthProvider>
    </ThemeProvider>
  </StrictMode>
)