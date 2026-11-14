import { useMemo, useRef } from "react";
import { ApiError, token } from "../api";
export const words = (s: string) => s.replace(/_/g, " ");
export const message = (e: unknown) =>
  e instanceof Error ? e.message : String(e);
/** The request may have reached the server although no response came back. */
const lostResponse = (e: unknown) => e instanceof ApiError && e.status === 0;

/**
 * One idempotency token per distinct action. The same action retried after a lost response sends the same
 * token, so the server returns what it already made instead of making (and, for a model, billing) a second one.
 * Once the server has answered or refused, the next attempt is a new action with a new token.
 */
export function useActionToken() {
  const held = useRef<{ key: string; token: string } | null>(null);
  return useMemo(
    () => ({
      take(key: string): string {
        if (held.current?.key !== key) held.current = { key, token: token() };
        return held.current.token;
      },
      done(error?: unknown) {
        if (!lostResponse(error)) held.current = null;
      },
    }),
    [],
  );
}
