import { useMemo } from "react";
import clsx from "clsx";

interface Props {
  value: number; // 0..1
  label?: string;
  size?: number;
  className?: string;
}

/**
 * Half-doughnut speedometer-style confidence gauge.
 * Green ≥ 0.85, Amber 0.70-0.84, Red < 0.70.
 */
export default function ConfidenceGauge({
  value,
  label,
  size = 140,
  className,
}: Props) {
  const v = Math.max(0, Math.min(1, value));

  const colorClass = useMemo(() => {
    if (v >= 0.85) return "text-veridian-400";
    if (v >= 0.70) return "text-amber-400";
    return "text-rose-500";
  }, [v]);

  const stroke = 12;
  const radius = (size - stroke) / 2;
  const circumference = Math.PI * radius;
  const offset = circumference * (1 - v);

  const cx = size / 2;
  const cy = size / 2;

  return (
    <div className={clsx("flex flex-col items-center", className)}>
      <svg width={size} height={size / 2 + stroke / 2}>
        <path
          d={`M ${stroke / 2} ${cy} A ${radius} ${radius} 0 0 1 ${
            size - stroke / 2
          } ${cy}`}
          fill="none"
          stroke="currentColor"
          strokeWidth={stroke}
          strokeLinecap="round"
          className="text-white/10"
        />
        <path
          d={`M ${stroke / 2} ${cy} A ${radius} ${radius} 0 0 1 ${
            size - stroke / 2
          } ${cy}`}
          fill="none"
          stroke="currentColor"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className={clsx(colorClass, "transition-all duration-700 ease-out")}
        />
      </svg>
      <div className="mt-[-22px] flex flex-col items-center">
        <div className={clsx("text-2xl font-bold", colorClass)}>
          {Math.round(v * 100)}%
        </div>
        {label && <div className="text-[11px] text-slate-400">{label}</div>}
      </div>
    </div>
  );
}
