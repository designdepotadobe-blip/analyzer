// Used for `ng build` with the "production" configuration (the frontend's own
// Railway service runs this build). REPLACE the URL below with the BACKEND
// service's Railway URL once it's deployed — the two are separate Railway
// services with separate URLs, even though both live in the same project. See
// the deployment guide, step "point the frontend at the backend".
export const environment = {
  production: true,
  apiBase: 'https://YOUR-BACKEND-SERVICE.up.railway.app',
};
