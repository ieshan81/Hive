"use client";

interface RingGaugeProps {
  value: number;
  size?: number;
  strokeWidth?: number;
  className?: string;
}

function gaugeColor(value: number): string {
  if (value >= 70) return "#10b981";
  if (value >= 40) return "#f59e0b";
  return "#ef4444";
}

export function RingGauge({
  value,
  size = 28,
  strokeWidth = 3,
  className,
}: RingGaugeProps) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (value / 100) * circumference;
  const color = gaugeColor(value);

  return (
    <svg width={size} height={size} className={className} aria-hidden>
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="rgba(255,255,255,0.08)"
        strokeWidth={strokeWidth}
      />
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
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ filter: `drop-shadow(0 0 4px ${color}66)` }}
      />
    </svg>
  );
}
