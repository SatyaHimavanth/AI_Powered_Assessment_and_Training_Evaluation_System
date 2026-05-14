import { useEffect, useState } from "react";

type ToastType = "info" | "success" | "error" | "warning";

interface Props {
  message: string;
  onClose: () => void;
  duration?: number; // milliseconds
  type?: ToastType;
  position?: "bottom-right" | "top-right";
}

function inferType(msg: string): ToastType {
  if (!msg) return "info";
  const s = msg.toLowerCase();
  const success = ["success", "imported", "created", "updated", "saved", "archived", "exported"];
  const error = ["fail", "failed", "error", "invalid", "cannot", "required", "missing", "not found", "denied", "forbidden"];
  const warn = ["warning", "expire", "pending", "not available", "violation"];
  if (success.some((k) => s.includes(k))) return "success";
  if (error.some((k) => s.includes(k))) return "error";
  if (warn.some((k) => s.includes(k))) return "warning";
  return "info";
}

export default function Toast({ message, onClose, duration = 5000, type, position = "bottom-right" }: Props) {
  const [visible, setVisible] = useState(false);
  const ttype: ToastType = type || inferType(message || "");

  useEffect(() => {
    if (!message) return;
    setVisible(true);
    const auto = setTimeout(() => {
      setVisible(false);
      // allow animation to finish
      setTimeout(() => onClose?.(), 250);
    }, duration);
    return () => clearTimeout(auto);
  }, [message, duration, onClose]);

  if (!message) return null;

  const posClass = position === "bottom-right" ? "bottom-6 right-6" : "top-6 right-6";

  const styleMap: Record<ToastType, string> = {
    info: "bg-blue-50 border-blue-200 text-blue-800",
    success: "bg-green-50 border-green-200 text-green-800",
    error: "bg-red-50 border-red-200 text-red-800",
    warning: "bg-amber-50 border-amber-200 text-amber-800",
  };

  return (
    <div className={`fixed z-50 ${posClass} max-w-sm w-full`}>
      <div
        role="status"
        className={`w-full border rounded-lg shadow-lg p-3 ${styleMap[ttype]} transition-all duration-200 transform ${visible ? "translate-y-0 opacity-100" : "translate-y-3 opacity-0"}`}
      >
        <div className="flex items-start gap-3">
          <div className="flex-1 text-sm leading-snug whitespace-pre-wrap">{message}</div>
          <button
            aria-label="Close"
            onClick={() => {
              setVisible(false);
              setTimeout(() => onClose(), 200);
            }}
            className="text-xl leading-none ml-2 opacity-80 hover:opacity-100"
          >
            &times;
          </button>
        </div>
      </div>
    </div>
  );
}
