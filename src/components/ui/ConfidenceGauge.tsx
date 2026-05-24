"use client";

interface ConfidenceGaugeProps {
  value: number;
  label: string;
}

export function ConfidenceGauge({ value, label }: ConfidenceGaugeProps) {
  const size = 88;
  const strokeWidth = 6;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (value / 100) * circumference;

  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative">
        <svg width={size} height={size} aria-hidden>
          <defs>
            <linearGradient id="confidenceGrad" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#00d1ff" />
              <stop offset="100%" stopColor="#8a2be2" />
            </linearGradient>
          </defs>
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="rgba(255,255,255,0.06)"
            strokeWidth={strokeWidth}
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="url(#confidenceGrad)"
            strokeWidth={strokeWidth}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
            style={{ filter: "drop-shadow(0 0 8px rgba(0,209,255,0.4))" }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-lg font-bold text-white">{value}%</span>
        </div>
      </div>
      <span className="text-[10px] text-slate-400 uppercase tracking-wider">{label}</span>
    </div>
  );
}
