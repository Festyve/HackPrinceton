import { useEffect, useState } from "react";
import { api } from "../api";
import type { Spend } from "../api";

const usd = (v?: number) => (v == null ? "?" : `$${v.toFixed(2)}`);

export function SpendLine() {
  const [s, setS] = useState<Spend | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    let live = true;
    api
      .spend()
      .then((r) => live && setS(r))
      .catch(() => live && setErr(true));
    return () => {
      live = false;
    };
  }, []);
  return (
    <p className="small muted" data-testid="spend-line">
      {err
        ? "The spend estimate could not be loaded from this server."
        : !s
          ? "Loading the spend estimate…"
          : !s.configured
            ? "No billed model route is configured on this server, so nothing can be spent. Recorded usage belongs to the saved run."
            : s.readable === false
              ? s.note
              : `Estimated model spend ${usd(s.spent_usd)} of the ${usd(s.cap_usd)} allowance across ${s.calls ?? 0} calls; automatic calls stop at ${usd(s.limit_in_force_usd)}. A conservative estimate at list prices, not a bill.`}
    </p>
  );
}
