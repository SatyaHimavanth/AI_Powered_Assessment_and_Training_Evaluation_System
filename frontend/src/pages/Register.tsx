import { useState } from "react";
import { Link } from "react-router-dom";
import api from "../api";

export default function Register() {
  const [form, setForm] = useState({
    username: "",
    email: "",
    contact_email: "",
    name: "",
    account: "",
    password: "",
    confirmPassword: "",
  });
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);
  const [sameEmail, setSameEmail] = useState(false);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setForm((prev) => {
      if (name === "email" && sameEmail) {
        return { ...prev, email: value, contact_email: value };
      }
      return { ...prev, [name]: value };
    });
  };

  const handleSameEmailToggle = (e: React.ChangeEvent<HTMLInputElement>) => {
    const checked = e.target.checked;
    setSameEmail(checked);
    if (checked) {
      setForm((prev) => ({ ...prev, contact_email: prev.email }));
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");

    if (form.password !== form.confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    if (form.password.length < 6) {
      setError("Password must be at least 6 characters");
      return;
    }

    setLoading(true);
    try {
      const res = await api.post("/auth/register", {
        username: form.username,
        email: form.email,
        contact_email: form.contact_email,
        name: form.name,
        account: form.account,
        password: form.password,
      });
      setSuccess(res.data.message);
      setForm({
        username: "",
        email: "",
        contact_email: "",
        name: "",
        account: "",
        password: "",
        confirmPassword: "",
      });
    } catch (err: unknown) {
      console.error(err);
      setError("Registration failed");
    } finally {
      setLoading(false);
    }
  };

  const inputClass =
    "w-full h-11 px-3.5 border border-[var(--color-border)] rounded-[var(--radius-sm)] bg-white text-sm placeholder:text-gray-400 hover:border-gray-400 focus:border-[var(--color-primary)] focus:ring-2 focus:ring-blue-100";

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg)] px-4">
      <div className="w-full max-w-[400px]">
        {/* Brand */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-[var(--radius)] bg-[var(--color-primary)] text-white text-xl font-bold mb-4">
            A
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">Create Account</h1>
          <p className="text-sm text-[var(--color-text-secondary)] mt-1">Register for assessment access</p>
        </div>

        {/* Card */}
        <div className="bg-white rounded-[var(--radius)] shadow-[var(--shadow-md)] p-8">

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-[var(--color-text)] mb-1.5">Full Name *</label>
              <input type="text" name="name" value={form.name} onChange={handleChange} className={inputClass} placeholder="John Doe" required />
            </div>
            <div>
              <label className="block text-sm font-medium text-[var(--color-text)] mb-1.5">Username *</label>
              <input type="text" name="username" value={form.username} onChange={handleChange} className={inputClass} placeholder="johndoe" required />
            </div>
            <div>
              <label className="block text-sm font-medium text-[var(--color-text)] mb-1.5">Email *</label>
              <input type="email" name="email" value={form.email} onChange={handleChange} className={inputClass} placeholder="john@example.com" required />
            </div>

            <div className="flex items-center gap-2">
              <input
                id="sameEmail"
                type="checkbox"
                checked={sameEmail}
                onChange={handleSameEmailToggle}
                className="h-4 w-4"
              />
              <label htmlFor="sameEmail" className="text-sm text-[var(--color-text-secondary)]">
                Click if both email and contact email are same
              </label>
            </div>

            <div>
              <label className="block text-sm font-medium text-[var(--color-text)] mb-1.5">Contact Email *</label>
              <input
                type="email"
                name="contact_email"
                value={form.contact_email}
                onChange={handleChange}
                className={`${inputClass} ${sameEmail ? 'opacity-50 cursor-not-allowed' : ''}`}
                placeholder="john@example.com"
                required
                disabled={sameEmail}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-[var(--color-text)] mb-1.5">Account</label>
              <input type="text" name="account" value={form.account} onChange={handleChange} className={inputClass} placeholder="e.g. India Ops" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium text-[var(--color-text)] mb-1.5">Password *</label>
                <input type="password" name="password" value={form.password} onChange={handleChange} className={inputClass} placeholder="Min 6 chars" required />
              </div>
              <div>
                <label className="block text-sm font-medium text-[var(--color-text)] mb-1.5">Confirm *</label>
                <input type="password" name="confirmPassword" value={form.confirmPassword} onChange={handleChange} className={inputClass} placeholder="Re-enter" required />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full h-11 bg-[var(--color-primary)] text-white text-sm font-medium rounded-[var(--radius-sm)] hover:bg-[var(--color-primary-hover)] disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer mt-2"
            >
              {loading ? (
                <span className="inline-flex items-center gap-2">
                  <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Submitting...
                </span>
              ) : "Create Account"}
            </button>

            {error && (
              <div className="flex items-center gap-2 bg-red-50 text-[var(--color-danger)] px-4 py-3 rounded-[var(--radius-sm)] mt-3 text-sm">
                <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                {error}
              </div>
            )}

            {success && (
              <div className="flex items-center gap-2 bg-green-50 text-[var(--color-success)] px-4 py-3 rounded-[var(--radius-sm)] mt-3 text-sm">
                <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                {success}
              </div>
            )}
          </form>
        </div>

        <p className="text-center text-sm text-[var(--color-text-secondary)] mt-6">
          Already have an account?{" "}
          <Link to="/login" className="text-[var(--color-primary)] font-medium hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
