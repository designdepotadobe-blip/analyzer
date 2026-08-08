// Used for `ng build` with the "production" configuration (the frontend's own
// Railway service runs this build). Points at the backend service's Railway
// domain — the two are separate Railway services with separate URLs, even
// though both live in the same project.
export const environment = {
  production: true,
  apiBase: 'https://analyzer-production-21a7.up.railway.app',
};
