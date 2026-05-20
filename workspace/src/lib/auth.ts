/**
 * JWT identity resolution for the customer portal.
 *
 * Token priority (highest → lowest):
 *  1. ?token=xxx   URL query parameter  (embedded / SSO redirect)
 *  2. localStorage "ym_token"           (persisted login)
 *  3. Guest mode                        (no token)
 *
 * The token is never verified on the client — verification happens on the
 * server.  We only decode the payload to extract display information.
 *
 * Integration patterns:
 *  A. Direct URL:      https://cs.example.com/?token=<jwt>
 *  B. postMessage:     parent sends { type: "YM_AUTH", token: "<jwt>" }
 *  C. localStorage:    set localStorage["ym_token"] before rendering
 *  D. Your own IdP:    redirect to IdP → IdP redirects back with ?token=<jwt>
 */

const STORAGE_KEY = 'ym_token';

export interface JWTClaims {
  sub: string;           // user_id
  name?: string;         // display name
  email?: string;
  exp?: number;
  iat?: number;
  [key: string]: unknown;
}

export interface Identity {
  token: string | null;
  userId: string;
  displayName: string;
  email: string;
  isGuest: boolean;
  claims: JWTClaims | null;
}

// ── Decode (no verification — server verifies) ─────────────────────────────

function decodePayload(token: string): JWTClaims | null {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(payload)) as JWTClaims;
  } catch {
    return null;
  }
}

function isExpired(claims: JWTClaims): boolean {
  if (!claims.exp) return false;
  return Date.now() / 1000 > claims.exp;
}

// ── Token persistence ──────────────────────────────────────────────────────

export function saveToken(token: string): void {
  localStorage.setItem(STORAGE_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(STORAGE_KEY);
}

export function getStoredToken(): string | null {
  return localStorage.getItem(STORAGE_KEY);
}

// ── Primary resolver ───────────────────────────────────────────────────────

let _cachedIdentity: Identity | null = null;

export function resolveIdentity(guestFallbackId?: string): Identity {
  if (_cachedIdentity) return _cachedIdentity;

  // 1. URL query param
  const params = new URLSearchParams(window.location.search);
  const urlToken = params.get('token');
  if (urlToken) {
    saveToken(urlToken);
    // Clean the token from the URL bar (replace history, don't add entry)
    const clean = new URL(window.location.href);
    clean.searchParams.delete('token');
    window.history.replaceState({}, '', clean.toString());
  }

  // 2. localStorage
  const token = urlToken || getStoredToken();
  if (token) {
    const claims = decodePayload(token);
    if (claims && !isExpired(claims)) {
      _cachedIdentity = {
        token,
        userId: claims.sub,
        displayName: (claims.name as string) || (claims.preferred_username as string) || claims.sub,
        email: (claims.email as string) || '',
        isGuest: false,
        claims,
      };
      return _cachedIdentity;
    }
    // Token expired — clear it
    clearToken();
    _cachedIdentity = null;
  }

  // 3. Guest fallback
  const gid = guestFallbackId || getOrCreateGuestId();
  _cachedIdentity = {
    token: null,
    userId: gid,
    displayName: '访客',
    email: '',
    isGuest: true,
    claims: null,
  };
  return _cachedIdentity;
}

/** Invalidate the in-memory cache (call after login / logout). */
export function resetIdentityCache(): void {
  _cachedIdentity = null;
}

// ── Guest ID — stable within the browser tab session ──────────────────────

function getOrCreateGuestId(): string {
  const KEY = 'ym_guest_id';
  let id = sessionStorage.getItem(KEY);
  if (!id) {
    id = 'guest-' + crypto.randomUUID().slice(0, 8);
    sessionStorage.setItem(KEY, id);
  }
  return id;
}

// ── postMessage listener — for iframe / parent-frame token injection ───────

export function listenForTokenInjection(onLogin: (identity: Identity) => void): () => void {
  const handler = (evt: MessageEvent) => {
    if (evt.data?.type !== 'YM_AUTH') return;
    const token = evt.data?.token as string | undefined;
    if (!token) return;
    saveToken(token);
    resetIdentityCache();
    const identity = resolveIdentity();
    onLogin(identity);
  };
  window.addEventListener('message', handler);
  return () => window.removeEventListener('message', handler);
}
