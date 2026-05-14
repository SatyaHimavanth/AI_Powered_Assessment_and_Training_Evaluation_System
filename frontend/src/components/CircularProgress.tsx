interface CircularProgressProps {
  percentage: number;
  label: string;
  size?: number;
  strokeWidth?: number;
}

export default function CircularProgress({
  percentage,
  label,
  size = 120,
  strokeWidth = 8,
}: CircularProgressProps) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (percentage / 100) * circumference;

  // Determine color based on percentage
  let color = "#ef4444"; // red < 40%
  if (percentage >= 70) color = "#10b981"; // green >= 70%
  else if (percentage >= 40) color = "#f59e0b"; // yellow 40-70%

  return (
    <div className="flex flex-col items-center gap-3" style={{ minWidth: 0 }}>
      <div style={{ position: "relative", width: size, height: size, maxWidth: "100%" }}>
        <svg viewBox={`0 0 ${size} ${size}`} preserveAspectRatio="xMidYMid meet" style={{ transform: "rotate(-90deg)", width: "100%", height: "100%" }}>
          {/* Background circle */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="#e5e7eb"
            strokeWidth={strokeWidth}
          />
          {/* Progress circle */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={strokeWidth}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            style={{ transition: "stroke-dashoffset 0.5s ease" }}
          />
        </svg>
        {/* Center text */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: "100%",
            height: "100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexDirection: "column",
          }}
        >
          <div style={{ fontSize: "18px", fontWeight: "bold", color }}>
            {percentage.toFixed(1)}%
          </div>
        </div>
      </div>
      <p className="text-sm font-medium text-gray-900 text-center" style={{ maxWidth: size, wordBreak: "break-word" }}>
        {label}
      </p>
    </div>
  );
}
