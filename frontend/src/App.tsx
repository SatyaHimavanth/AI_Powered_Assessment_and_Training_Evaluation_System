import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import api from "./api";
import Login from "./pages/Login";
import Register from "./pages/Register";
import AdminHome from "./pages/AdminHome";
import UserHome from "./pages/UserHome";

function ProtectedRoute({ children, role }: { children: React.ReactNode; role: string }) {
  const [status, setStatus] = useState<"checking" | "authorized" | "denied">("checking");

  useEffect(() => {
    let active = true;
    api.get("/auth/me")
      .then((response) => {
        if (!active) return;
        const actualRole = response.data?.role;
        if (typeof actualRole !== "string") {
          setStatus("denied");
          return;
        }
        setStatus(actualRole === role ? "authorized" : "denied");
      })
      .catch(() => {
        if (!active) return;
        setStatus("denied");
      });

    return () => {
      active = false;
    };
  }, [role]);

  if (status === "checking") {
    return (
      <main className="min-h-screen flex items-center justify-center" role="status" aria-live="polite">
        Restoring your session…
      </main>
    );
  }
  if (status === "denied") return <Navigate to="/login" replace />;

  return <>{children}</>;
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route
          path="/admin"
          element={
            <ProtectedRoute role="admin">
              <AdminHome />
            </ProtectedRoute>
          }
        />
        <Route
          path="/user"
          element={
            <ProtectedRoute role="user">
              <UserHome />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
