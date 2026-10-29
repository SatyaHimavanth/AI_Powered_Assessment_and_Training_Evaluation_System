import axios from "axios";

export const API_BASE =
  import.meta.env.VITE_API_BASE ||
  (import.meta.env.DEV ? "http://localhost:8000" : "/api");
let refreshPromise: Promise<void> | null = null;

function refreshAccessToken(): Promise<void> {
  if (!refreshPromise) {
    const refresh = async () => {
      await axios.post(
        `${API_BASE}/auth/refresh`,
        null,
        { withCredentials: true, timeout: 10_000 },
      );
    };
    const lockManager = navigator.locks;
    refreshPromise = (lockManager
      ? lockManager.request("assessment-auth-refresh", refresh)
      : refresh()
    ).finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
});

// Remove credentials saved by older builds; both tokens are now HttpOnly cookies.
if (typeof window !== "undefined") {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
  localStorage.removeItem("role");
}

// Handle 401 - try refresh (skip for auth endpoints)
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    const isAuthEndpoint =
      originalRequest?.url?.includes("/auth/login") ||
      originalRequest?.url?.includes("/auth/register") ||
      originalRequest?.url?.includes("/auth/refresh") ||
      originalRequest?.url?.includes("/auth/logout");

    if (error.response?.status === 401 && originalRequest && !originalRequest._retry && !isAuthEndpoint) {
      originalRequest._retry = true;
      try {
        await refreshAccessToken();
        return api(originalRequest);
      } catch {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  },
);

export default api;
