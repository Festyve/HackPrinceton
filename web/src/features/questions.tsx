import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { QuestionAnswer, Runtime } from "../api";
import { Chips } from "../common";
import { words, message, useActionToken } from "./operation";

const SUPPORT: Record<string, string> = {
  checked: "Confirmed by a check",
  contradicted: "Contradicted by a check",
  cited: "Cited · not machine-checked",
  interpretation: "Model's interpretation",
  unsupported: "Unsupported",
};
const ANSWER_STATUS: Record<string, string> = {
  pending: "Answering",
  answered: "Answered",
  insufficient_evidence: "Evidence insufficient",
  unavailable: "Not answered",
  failed: "No answer",
};

function Answer({
  a,
  open,
  unknown,
  onToggle,
  onRefresh,
}: {
  a: QuestionAnswer;
  open: boolean;
  unknown: boolean;
  onToggle: (open: boolean) => void;
  onRefresh: () => void;
}) {
  const limits = a.limitations ?? [];
  const plain = a.status === "unavailable" || a.status === "failed";
  const lost = unknown && a.status === "pending";
  return (
    <details
      className="qa-answer"
      open={open}
      onToggle={(e) => {
        if (e.currentTarget.open !== open) onToggle(e.currentTarget.open);
      }}
      data-testid="question-answer"
      data-status={a.status}
    >
      <summary>
        <b>{a.question}</b>
        <span className="tag">
          {a.inference_label ?? words(a.inference_mode)}
        </span>
        <span className="tag">
          {lost
            ? "Status unknown"
            : (ANSWER_STATUS[a.status] ?? words(a.status))}
        </span>
      </summary>
      {a.status === "pending" && !lost && (
        <p role="status" className="small muted">
          Answering from this case's evidence. At most three model calls.
        </p>
      )}
      {lost && (
        <p role="alert" className="small amber">
          The server could not be reached for this question's status, so it is
          not known whether it was answered.{" "}
          <button
            className="linkish"
            data-testid="btn-question-refresh"
            onClick={onRefresh}
          >
            Check again
          </button>
        </p>
      )}
      {a.answer && <p className="qa-text">{a.answer}</p>}
      {plain && limits[0] && <p className="qa-text">{limits[0]}</p>}
      {a.error && <p className="small bad">{a.error}</p>}
      {!!a.claims?.length && (
        <ul className="qa-claims">
          {a.claims.map((c, i) => (
            <li key={i} data-support={c.support}>
              <span className={`support ${c.support}`}>
                {SUPPORT[c.support] ?? words(c.support)}
              </span>
              <span>{c.text}</span>
              <Chips ids={c.evidence_ids} />
              {c.basis && <small className="muted">{c.basis}</small>}
            </li>
          ))}
        </ul>
      )}
      {!plain && limits.length > 0 && (
        <details className="qa-limits">
          <summary>
            {limits.length} stated limit{limits.length === 1 ? "" : "s"}
          </summary>
          <ul>
            {limits.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </details>
      )}
      {!!a.follow_up_evidence?.length && (
        <p className="small muted">
          Evidence that would help: {a.follow_up_evidence.join("; ")}
        </p>
      )}
    </details>
  );
}

export function QuestionPanel({
  caseId,
  available,
  runtime,
}: {
  caseId: string;
  available: boolean;
  runtime: Runtime | null;
}) {
  const [items, setItems] = useState<QuestionAnswer[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Saved answers load closed so they do not cover the evidence; the one just asked opens.
  const [openId, setOpenId] = useState<string | null>(null);
  // questions whose status could not be refreshed: shown as unknown, never as still answering
  const [unknown, setUnknown] = useState<string[]>([]);
  const alive = useRef(0);
  const ask = useActionToken();

  const put = useCallback((a: QuestionAnswer) => {
    setItems((cur) =>
      cur.some((x) => x.question_id === a.question_id)
        ? cur.map((x) => (x.question_id === a.question_id ? a : x))
        : [...cur, a],
    );
  }, []);

  /**
   * Poll one pending question until the server gives it a final status. A failed request is retried with a
   * growing pause. If the server stays unreachable, or five minutes pass, the question is marked "status
   * unknown": it is never left looking as if it were still being answered.
   */
  const follow = useCallback(
    async (a: QuestionAnswer, gen: number) => {
      let cur = a;
      let failures = 0;
      const giveUpAt = Date.now() + 5 * 60_000;
      const id = a.question_id;
      setUnknown((u) => u.filter((x) => x !== id));
      while (cur.status === "pending") {
        if (failures >= 6 || Date.now() > giveUpAt) {
          setUnknown((u) => (u.includes(id) ? u : [...u, id]));
          return;
        }
        const pause = Math.min(1500 * 2 ** failures, 12_000);
        await new Promise((r) => window.setTimeout(r, pause));
        if (gen !== alive.current) return;
        try {
          cur = await api.question(caseId, id);
          failures = 0;
        } catch {
          failures += 1;
          continue;
        }
        if (gen !== alive.current) return;
        put(cur);
      }
    },
    [caseId, put],
  );

  /** What the server has for this case, and follow whichever question is still pending. */
  const load = useCallback(
    async (gen: number) => {
      const r = await api.questions(caseId);
      if (gen !== alive.current) return;
      setItems(r.questions);
      const pending = r.questions.find((x) => x.status === "pending");
      if (pending) {
        setBusy(true);
        try {
          await follow(pending, gen);
        } finally {
          if (gen === alive.current) setBusy(false);
        }
      }
    },
    [caseId, follow],
  );

  useEffect(() => {
    const gen = ++alive.current;
    setItems([]);
    setErr(null);
    setText("");
    setBusy(false);
    setOpenId(null);
    setUnknown([]);
    ask.done();
    if (!available) return;
    load(gen).catch(
      (e: unknown) => gen === alive.current && setErr(message(e)),
    );
    return () => {
      alive.current += 1;
    };
  }, [caseId, available, load, ask]);

  const submit = async () => {
    const question = text.trim();
    if (!question || busy || !available) return;
    const gen = alive.current;
    setBusy(true);
    setErr(null);
    try {
      // the same text sent again after a lost response is the same question, not a second one
      const a = await api.ask(caseId, question, ask.take(question));
      if (gen !== alive.current) return;
      ask.done();
      put(a);
      setOpenId(a.question_id);
      setText("");
      await follow(a, gen);
    } catch (e) {
      if (gen !== alive.current) return;
      ask.done(e);
      // The server's own words. A refusal can mean another question is pending, the case's question limit,
      // or a case state that does not take questions; this panel does not guess which.
      setErr(message(e));
      try {
        await load(gen); // show what the server actually has, including a question asked from elsewhere
      } catch {
        /* the first error stays on screen */
      }
    } finally {
      if (gen === alive.current) setBusy(false);
    }
  };

  const caps = runtime?.capabilities?.questions;
  const max = caps?.max_question_chars ?? 1000;
  const model = caps?.model_answers; // undefined when the server's status could not be loaded
  const reason = !available
    ? "Questions become available after the report is drafted."
    : busy
      ? "Answering from this case's evidence…"
      : model === "CONFIGURED"
        ? "A model answers from this case's evidence only. Each claim carries a label saying whether a check confirmed it. A question never changes the report."
        : model === "BLOCKED"
          ? "No model is configured on this server, so a question is recorded and returned unanswered. The cited explanations need no model."
          : "Whether a model is configured on this server is not known here. A question is sent, and its answer says whether a model answered it.";
  return (
    <section
      className="qa qa-dock"
      aria-label="Questions"
      data-testid="question-composer"
    >
      {items.length > 0 && (
        <div className="qa-answers" data-testid="question-answers">
          <p className="eyebrow">
            {items.length} question{items.length === 1 ? "" : "s"} asked about
            this case · kept apart from the report
          </p>
          {items.map((a) => (
            <Answer
              key={a.question_id}
              a={a}
              open={a.question_id === openId}
              unknown={unknown.includes(a.question_id)}
              onRefresh={() => {
                const gen = alive.current;
                setBusy(true);
                follow(a, gen).finally(
                  () => gen === alive.current && setBusy(false),
                );
              }}
              onToggle={(o) =>
                setOpenId((cur) =>
                  o ? a.question_id : cur === a.question_id ? null : cur,
                )
              }
            />
          ))}
        </div>
      )}
      <form
        className="questions"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div>
          <label htmlFor="case-question">Ask about this evidence</label>
          <p id="question-reason" role={err ? "alert" : undefined}>
            {err ?? reason}
          </p>
        </div>
        <div className="composer">
          <input
            id="case-question"
            type="text"
            value={text}
            maxLength={max}
            onChange={(e) => setText(e.target.value)}
            placeholder="What can these records establish?"
            disabled={!available || busy}
            aria-describedby="question-reason"
          />
          <button
            type="submit"
            data-testid="btn-ask"
            disabled={!available || busy || !text.trim()}
          >
            {busy ? "Answering…" : "Ask"}
          </button>
        </div>
      </form>
    </section>
  );
}
