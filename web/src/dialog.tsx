import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

/** Native modal supplies focus containment, Escape and return-to-trigger behavior. */
export function Dialog({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = ref.current;
    const trigger = document.activeElement as HTMLElement | null;
    el?.showModal();
    return () => {
      el?.close();
      if (trigger?.isConnected) trigger.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={wide ? "drawer wide" : "drawer"}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <header className="drawer-head">
        <h2>{title}</h2>
        <button onClick={onClose} aria-label={`Close ${title}`}>
          Close <span aria-hidden>×</span>
        </button>
      </header>
      {children}
    </dialog>
  );
}
