import { cn } from "@/lib/utils";

interface GlassPanelProps {
  children: React.ReactNode;
  className?: string;
  title?: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
  subtitle?: string;
}

export function GlassPanel({
  children,
  className,
  title,
  icon,
  action,
  subtitle,
}: GlassPanelProps) {
  return (
    <section className={cn("glass-panel rounded-xl overflow-hidden", className)}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 px-4 pt-4 pb-2 border-b border-white/5">
          <div className="flex items-center gap-2 min-w-0">
            {icon && (
              <span className="flex-shrink-0 text-hive-cyan opacity-90">{icon}</span>
            )}
            <div className="min-w-0">
              {title && (
                <h2 className="text-[11px] font-semibold tracking-[0.14em] text-slate-300 uppercase truncate">
                  {title}
                </h2>
              )}
              {subtitle && (
                <p className="text-[10px] text-slate-500 mt-0.5">{subtitle}</p>
              )}
            </div>
          </div>
          {action && <div className="flex-shrink-0">{action}</div>}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}
