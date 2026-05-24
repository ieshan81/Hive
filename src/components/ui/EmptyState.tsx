interface EmptyStateProps {
  message: string;
  className?: string;
}

export function EmptyState({ message, className = "" }: EmptyStateProps) {
  return (
    <div
      className={`flex flex-col items-center justify-center rounded-lg border border-dashed border-white/10 bg-white/2 px-4 py-8 text-center ${className}`}
    >
      <p className="text-xs text-slate-500 max-w-xs leading-relaxed">{message}</p>
    </div>
  );
}
