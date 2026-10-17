// Auth0 Actions > Triggers > post-login. Deploy and attach to Login flow.
// Secrets: CHATGPT_CLIENT_ID, PORTAL_CLIENT_ID, ALLOWED_USER_IDS (JSON array).
// Example ALLOWED_USER_IDS: ["auth0|YOUR_USER_ID"] -- use IDs, never emails.
exports.onExecutePostLogin = async (event, api) => {
  const clients = [event.secrets.CHATGPT_CLIENT_ID, event.secrets.PORTAL_CLIENT_ID];
  if (!clients.includes(event.client.client_id)) return;

  let allowed;
  try {
    allowed = JSON.parse(event.secrets.ALLOWED_USER_IDS);
  } catch {
    return api.access.deny('Private integration allowlist is not configured.');
  }
  if (!Array.isArray(allowed) || !allowed.includes(event.user.user_id)) {
    return api.access.deny('This integration is private.');
  }

  // Refresh requests have no authorization-request PKCE challenge.
  if (event.transaction?.protocol === 'oauth2-refresh-token') return;
  const query = event.request?.query || {};
  if (query.response_type !== 'code' || query.code_challenge_method !== 'S256' ||
      typeof query.code_challenge !== 'string' ||
      !/^[A-Za-z0-9_-]{43}$/.test(query.code_challenge)) {
    return api.access.deny('Authorization code with S256 PKCE is required.');
  }
};
