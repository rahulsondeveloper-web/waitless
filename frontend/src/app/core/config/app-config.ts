/**
 * Runtime endpoints. In development the Angular dev server proxies these paths to FastAPI
 * (see proxy.conf.json); in production Nginx does the same, so relative URLs work everywhere.
 */
export const APP_CONFIG = {
  apiBase: '/api/v1',
  socketPath: '/socket.io',
  socketNamespace: '/rt',
  platformName: 'WaitLess',
  platformTagline: 'Skip the Wait. Dine Delightfully!',
} as const;
