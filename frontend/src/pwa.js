/**
 * PWA registration for VN Stock AI Analyzer.
 *
 * Registers /sw.js in production builds only — keeps the dev server snappy
 * and avoids caching half-built assets while iterating with Vite HMR.
 *
 * Import this once from `main.jsx` (side-effect import):
 *   import './pwa.js';
 */

export function registerServiceWorker() {
  if (typeof window === 'undefined') return;
  if (!('serviceWorker' in navigator)) return;
  if (!import.meta.env.PROD) return;

  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js')
      .then((registration) => {
        // Listen for updates and prompt the new worker to activate.
        registration.addEventListener('updatefound', () => {
          const newWorker = registration.installing;
          if (!newWorker) return;
          newWorker.addEventListener('statechange', () => {
            if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
              // A new SW is waiting — tell it to skip waiting so the next
              // navigation picks up the fresh assets.
              newWorker.postMessage({ type: 'SKIP_WAITING' });
            }
          });
        });
      })
      .catch((err) => {
        // Don't crash the app if registration fails — log and move on.
        console.warn('[pwa] Service worker registration failed:', err);
      });
  });

  // Reload once the new SW takes control so users see the updated build.
  let refreshing = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (refreshing) return;
    refreshing = true;
    window.location.reload();
  });
}

// Auto-register on import — `import './pwa.js'` is enough.
registerServiceWorker();
