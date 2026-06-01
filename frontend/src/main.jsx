import React from 'react';
import ReactDOM from 'react-dom/client';
import { ThemeProvider } from './ThemeContext.jsx';
import { ToastProvider } from './components/Toast/ToastProvider.jsx';
import { ErrorBoundary } from './components/ErrorBoundary.jsx';
import App from './App.jsx';
import './App.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <ThemeProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </ThemeProvider>
    </ErrorBoundary>
  </React.StrictMode>
);
