const TOKEN_KEY = "vwdash_token";
const USERNAME_KEY = "vwdash_username";
const IS_ADMIN_KEY = "vwdash_is_admin";

let _mem: { token: string | null; username: string | null; isAdmin: boolean | null } = {
  token: null,
  username: null,
  isAdmin: null,
};

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  if (_mem.token !== null) return _mem.token;
  _mem.token = localStorage.getItem(TOKEN_KEY);
  return _mem.token;
}

export function getUsername(): string | null {
  if (typeof window === "undefined") return null;
  if (_mem.username !== null) return _mem.username;
  _mem.username = localStorage.getItem(USERNAME_KEY);
  return _mem.username;
}

export function isAdmin(): boolean {
  if (typeof window === "undefined") return false;
  if (_mem.isAdmin !== null) return _mem.isAdmin;
  _mem.isAdmin = localStorage.getItem(IS_ADMIN_KEY) === "true";
  return _mem.isAdmin;
}

export function setAuth(token: string, username: string, admin: boolean): void {
  _mem = { token, username, isAdmin: admin };
  if (typeof window !== "undefined") {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USERNAME_KEY, username);
    localStorage.setItem(IS_ADMIN_KEY, String(admin));
  }
}

export function clearAuth(): void {
  _mem = { token: null, username: null, isAdmin: null };
  if (typeof window !== "undefined") {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USERNAME_KEY);
    localStorage.removeItem(IS_ADMIN_KEY);
  }
}

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// Backward-compat aliases used in older code paths
export function setToken(token: string): void {
  setAuth(token, getUsername() ?? "", isAdmin());
}

export function clearToken(): void {
  clearAuth();
}
