const TOKEN_KEY = "vwdash_access_token";

let _memToken: string | null = null;

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  if (_memToken !== null) return _memToken;
  _memToken = localStorage.getItem(TOKEN_KEY);
  return _memToken;
}

export function setToken(token: string): void {
  _memToken = token;
  if (typeof window !== "undefined") {
    localStorage.setItem(TOKEN_KEY, token);
  }
}

export function clearToken(): void {
  _memToken = null;
  if (typeof window !== "undefined") {
    localStorage.removeItem(TOKEN_KEY);
  }
}

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
