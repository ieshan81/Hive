"use client";

import { useEffect, useState } from "react";
import { KeyRound } from "lucide-react";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { checkServerOperatorProxy } from "@/lib/apiClient";
import {
  clearSessionOperatorToken,
  getSessionOperatorToken,
  hasSessionOperatorToken,
  setSessionOperatorToken,
} from "@/lib/operatorAuth";

export function OperatorAuthPanel() {
  const [serverProxy, setServerProxy] = useState<boolean | null>(null);
  const [tokenInput, setTokenInput] = useState("");
  const [hasSession, setHasSession] = useState(false);

  useEffect(() => {
    checkServerOperatorProxy().then(setServerProxy);
    setHasSession(hasSessionOperatorToken());
    setTokenInput(getSessionOperatorToken() || "");
  }, []);

  function saveSession() {
    setSessionOperatorToken(tokenInput);
    setHasSession(true);
  }

  function clearSession() {
    clearSessionOperatorToken();
    setTokenInput("");
    setHasSession(false);
  }

  return (
    <GlassPanel title="Operator authorization" icon={<KeyRound className="h-4 w-4" />}>
      <p className="text-[10px] text-slate-400 mb-2">
        Dangerous actions need authorization. The real backend secret must never appear in this public
        page source. Prefer server-side proxy (OPERATOR_SECRET on frontend service only).
      </p>
      {serverProxy === true && (
        <p className="text-[11px] text-emerald-400/90 mb-2">
          Server-side operator proxy is configured. Mutating actions use the proxy — no browser secret.
        </p>
      )}
      {serverProxy === false && (
        <p className="text-[11px] text-amber-300/90 mb-2">
          No server proxy. Enter an operator session token below (stored only in this browser tab).
        </p>
      )}
      <label className="block text-[10px] text-slate-500 mb-1">Operator session token (optional)</label>
      <input
        type="password"
        value={tokenInput}
        onChange={(e) => setTokenInput(e.target.value)}
        placeholder="Paste token if not using server proxy"
        className="w-full text-[10px] bg-black/40 border border-white/10 rounded px-2 py-1 mb-2"
      />
      <div className="flex gap-2">
        <button
          type="button"
          onClick={saveSession}
          className="text-[10px] border border-hive-cyan/30 rounded px-2 py-1 text-hive-cyan"
        >
          Save session token
        </button>
        <button type="button" onClick={clearSession} className="text-[10px] text-slate-500">
          Clear
        </button>
      </div>
      {hasSession && (
        <p className="text-[9px] text-slate-500 mt-2">Session token saved for this tab only.</p>
      )}
    </GlassPanel>
  );
}
