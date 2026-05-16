import { Link, Route, Routes, useLocation } from "react-router-dom";
import clsx from "clsx";
import { Activity, BarChart3, FileText, Sliders } from "lucide-react";

import Dashboard from "./pages/Dashboard";
import AuditLog from "./pages/AuditLog";
import Analytics from "./pages/Analytics";
import Settings from "./pages/Settings";

function NavTab({
  to,
  label,
  icon,
}: {
  to: string;
  label: string;
  icon: JSX.Element;
}) {
  const { pathname } = useLocation();
  const active =
    to === "/" ? pathname === "/" : pathname.startsWith(to);
  return (
    <Link
      to={to}
      className={clsx(
        "flex items-center gap-2 rounded-xl px-3 py-1.5 text-sm transition-colors",
        active
          ? "bg-veridian-600/30 text-veridian-100 ring-1 ring-veridian-500/50"
          : "text-slate-300 hover:bg-white/5",
      )}
    >
      {icon}
      <span>{label}</span>
    </Link>
  );
}

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-30 border-b border-white/5 bg-ink-900/80 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="relative flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-veridian-600/20 ring-1 ring-veridian-500/40 shadow-lg shadow-black/20">
              <img
                src="/plutuslogo.png"
                alt="PlutusAudit AI"
                className="h-full w-full object-contain p-0.5"
                width={40}
                height={40}
                decoding="async"
              />
            </div>
            <div>
              <div className="text-sm font-semibold tracking-wide text-white">
                PlutusAudit AI
              </div>
              <div className="text-[11px] text-slate-400">
                Autonomous invoice assurance · v1.0
              </div>
            </div>
          </div>

          <nav className="flex items-center gap-1">
            <NavTab to="/" label="Dashboard" icon={<Activity className="h-4 w-4" />} />
            <NavTab
              to="/audit"
              label="Audit Log"
              icon={<FileText className="h-4 w-4" />}
            />
            <NavTab
              to="/analytics"
              label="Analytics"
              icon={<BarChart3 className="h-4 w-4" />}
            />
            <NavTab
              to="/settings"
              label="Settings"
              icon={<Sliders className="h-4 w-4" />}
            />
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/audit" element={<AuditLog />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>

      <footer className="border-t border-white/5 bg-ink-900/60">
        <div className="mx-auto max-w-7xl px-6 py-4 text-xs text-slate-400 flex flex-wrap items-center justify-between gap-3">
          <span className="flex items-center gap-2">
            <img
              src="/plutuslogo.png"
              alt=""
              aria-hidden
              className="h-5 w-5 shrink-0 object-contain opacity-90"
              width={20}
              height={20}
              decoding="async"
            />
            PlutusAudit AI · Enterprise invoice controls and audit assurance
          </span>
          <span className="mono">
            AI extraction · GL classification · tamper-evident audit trail
          </span>
        </div>
      </footer>
    </div>
  );
}
