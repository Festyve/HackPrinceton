import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { SensorPoint, SensorStreams } from "../api";
import { Chips, EvidenceCtx, hhmmss } from "../common";
import { words, message } from "./operation";

const W = 640;
const H = 250;
const M = { l: 38, r: 14, t: 26, b: 26 };
const PLOT_L = M.l;
const PLOT_R = W - M.r;
const ms = (s: string) => Date.parse(s);
const clampX = (x: number) => Math.min(PLOT_R, Math.max(PLOT_L, x));

function nearest(points: SensorPoint[], t: number): SensorPoint | null {
  let best: SensorPoint | null = null;
  let d = Infinity;
  for (const p of points) {
    const x = Math.abs(ms(p.ts) - t);
    if (x < d) {
      d = x;
      best = p;
    }
  }
  return best;
}

// The headline says no more than the server's status does. "consistent" means the check found no
// disagreement of two or more consecutive readings; single differing readings are counted beside it.
const TEMP_HEADLINE: Record<string, string> = {
  discrepancy_unexplained:
    "The two records disagree, and no stated maintenance explains it.",
  discrepancy_explained:
    "No unexplained disagreement was found. The records differ inside a stated maintenance window.",
  consistent: "No unexplained disagreement was found between the two records.",
};
const DISCREPANCY: Record<string, string> = {
  unexplained: "Unexplained",
  explained_maintenance: "Inside a maintenance window",
  isolated_reading: "A single reading",
};
const EXPOSURE: Record<string, string> = {
  independent_witness: "independent witness",
  host_local_writable: "local record, writable on its host",
};
const HOUR = 3600_000;
const TICK_STEPS = [0.25, 0.5, 1, 2, 3, 6, 12, 24, 48, 96, 168].map(
  (h) => h * HOUR,
);

export function TemperatureRecords({
  caseId,
  stateKey,
}: {
  caseId: string;
  stateKey: string;
}) {
  const [data, setData] = useState<SensorStreams | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // pointer: a time. keyboard: an index into the series being stepped through, so two readings with the
  // same timestamp are both reachable and the first key press lands on a reading instead of skipping one.
  const [at, setAt] = useState<number | null>(null);
  const [step, setStep] = useState<number | null>(null);
  const open = useContext(EvidenceCtx);
  const svg = useRef<SVGSVGElement | null>(null);
  useEffect(() => {
    let live = true;
    setData(null);
    setErr(null);
    setAt(null);
    setStep(null);
    api
      .sensorStreams(caseId)
      .then((r) => live && setData(r))
      .catch((e: unknown) => live && setErr(message(e)));
    return () => {
      live = false;
    };
  }, [caseId, stateKey]);

  const geo = useMemo(() => {
    if (!data?.applicable) return null;
    const stored = data.series.find((s) => s.key === "stored")?.points ?? [];
    const ref = data.series.find((s) => s.key === "reference")?.points ?? [];
    const all = [...stored, ...ref];
    if (!all.length) return null;
    const [lo, hi] = data.permitted_range_c ?? [0, 0];
    const t0 = Math.min(...all.map((p) => ms(p.ts)));
    const t1 = Math.max(...all.map((p) => ms(p.ts)));
    const y0 = Math.floor(Math.min(lo, ...all.map((p) => p.temp_c)) - 0.5);
    const y1 = Math.ceil(Math.max(hi, ...all.map((p) => p.temp_c)) + 0.5);
    const x = (t: number) =>
      PLOT_L + ((t - t0) / Math.max(1, t1 - t0)) * (PLOT_R - PLOT_L);
    const y = (v: number) =>
      H - M.b - ((v - y0) / Math.max(1, y1 - y0)) * (H - M.t - M.b);
    const path = (pts: SensorPoint[]) =>
      pts
        .map(
          (p, i) =>
            `${i ? "L" : "M"}${x(ms(p.ts)).toFixed(1)} ${y(p.temp_c).toFixed(1)}`,
        )
        .join(" ");
    const range = y1 - y0;
    const yStep = range > 60 ? 20 : range > 30 ? 10 : range > 12 ? 4 : 2;
    const yTicks: number[] = [];
    for (let v = Math.ceil(y0 / yStep) * yStep; v <= y1; v += yStep)
      yTicks.push(v);
    // at most eight time labels, however long the capture is
    const span = Math.max(1, t1 - t0);
    const every =
      TICK_STEPS.find((s) => span / s <= 8) ??
      Math.ceil(span / 8 / HOUR) * HOUR;
    const xTicks: number[] = [];
    for (let t = Math.ceil(t0 / every) * every; t <= t1; t += every)
      xTicks.push(t);
    return {
      stored,
      ref,
      t0,
      t1,
      lo,
      hi,
      x,
      y,
      path,
      yTicks,
      xTicks,
      days: span > 24 * HOUR,
    };
  }, [data]);

  if (err)
    return (
      <div className="banner err small" role="alert">
        The temperature records could not be loaded: {err}
      </div>
    );
  if (!data || !data.applicable) return null;

  const all = data.discrepancies ?? [];
  const unexplained = all.filter((d) => d.classification === "unexplained");
  const isolated = all.filter((d) => d.classification === "isolated_reading");
  const notAssessable = data.status === "not_assessable";
  const refSeries = data.series.find((s) => s.key === "reference");
  const storedSeries = data.series.find((s) => s.key === "stored");
  const cut = data.series.filter((s) => s.truncated);
  const limits = (data.coverage_limits ?? []).filter(
    (l) => l !== data.status_reason,
  );

  // what is stepped through with the arrow keys: the reference readings, or the stored ones if there are none
  const base = geo ? (geo.ref.length ? geo.ref : geo.stored) : [];
  const baseIsRef = !!geo && geo.ref.length > 0;
  const firstStep = () => {
    if (!unexplained[0]) return 0;
    const i = base.findIndex((p) => ms(p.ts) >= ms(unexplained[0].start));
    return i < 0 ? 0 : i;
  };
  const move = (clientX: number) => {
    if (!geo || !svg.current) return;
    const box = svg.current.getBoundingClientRect();
    const vx = ((clientX - box.left) / Math.max(1, box.width)) * W;
    const f = Math.min(1, Math.max(0, (vx - PLOT_L) / (PLOT_R - PLOT_L)));
    setStep(null);
    setAt(geo.t0 + f * (geo.t1 - geo.t0));
  };
  const key = (dir: 1 | -1) => {
    if (!base.length) return;
    const next =
      step == null
        ? firstStep()
        : Math.min(base.length - 1, Math.max(0, step + dir));
    setStep(next);
    setAt(ms(base[next].ts));
  };
  const pinned = step != null ? (base[step] ?? null) : null;
  const hoverRef =
    geo && at != null
      ? baseIsRef && pinned
        ? pinned
        : nearest(geo.ref, at)
      : null;
  const hoverStored =
    geo && at != null
      ? !baseIsRef && pinned
        ? pinned
        : nearest(geo.stored, at)
      : null;
  const hx = geo && at != null ? geo.x(at) : null;
  const stamp = (t: number) => {
    const iso = new Date(t).toISOString();
    return geo?.days
      ? `${iso.slice(5, 10)} ${iso.slice(11, 16)}`
      : iso.slice(11, 16);
  };

  const headline = notAssessable
    ? (data.status_reason ??
      "The two records could not be compared in this evidence view.")
    : (TEMP_HEADLINE[data.status] ?? words(data.status)) +
      (isolated.length && !unexplained.length
        ? ` ${isolated.length} single reading${isolated.length === 1 ? "" : "s"} differed; see the table.`
        : "");

  return (
    <section className="panel temp-records" data-testid="temperature-records">
      <div className="column-title">
        <h2>Two temperature records</h2>
        <span>{data.sensor} · UTC</span>
      </div>
      <p
        className={
          "headline " +
          (notAssessable ? "amber" : unexplained.length ? "bad" : "")
        }
        data-testid="temperature-status"
      >
        {headline}
      </p>
      <ul className="temp-legend" aria-label="Series">
        {[refSeries, storedSeries].map(
          (s) =>
            s && (
              <li key={s.key}>
                <i
                  className={`key ${s.key === "reference" ? "ref" : "stored"}`}
                  aria-hidden
                />
                {s.label}
                <small>
                  {!s.present
                    ? "not in this bundle"
                    : (EXPOSURE[s.tamper_exposure ?? ""] ?? "")}
                </small>
              </li>
            ),
        )}
      </ul>
      {geo && (
        <div className="temp-plot">
          <svg
            ref={svg}
            viewBox={`0 0 ${W} ${H}`}
            role="img"
            tabIndex={0}
            aria-label={`Temperature over time for ${data.sensor}: the reference logger and the readings stored on the hub. Use the arrow keys to read values.`}
            onPointerMove={(e) => move(e.clientX)}
            onPointerLeave={() => {
              if (step == null) setAt(null);
            }}
            onBlur={() => {
              setStep(null);
              setAt(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowRight") key(1);
              else if (e.key === "ArrowLeft") key(-1);
              else return;
              e.preventDefault();
            }}
          >
            <rect
              className="band"
              x={PLOT_L}
              width={PLOT_R - PLOT_L}
              y={geo.y(geo.hi)}
              height={Math.max(0, geo.y(geo.lo) - geo.y(geo.hi))}
            />
            {geo.yTicks.map((v) => (
              <g key={v}>
                <line
                  className="grid"
                  x1={PLOT_L}
                  x2={PLOT_R}
                  y1={geo.y(v)}
                  y2={geo.y(v)}
                />
                <text
                  className="tick"
                  x={PLOT_L - 6}
                  y={geo.y(v) + 3}
                  textAnchor="end"
                >
                  {v}
                </text>
              </g>
            ))}
            <text className="tick" x={PLOT_L - 6} y={M.t - 12} textAnchor="end">
              °C
            </text>
            <text
              className="region-label"
              x={PLOT_L + 5}
              y={geo.y(geo.hi) + 11}
            >
              Permitted {geo.lo}–{geo.hi} °C
            </text>
            {(data.maintenance_windows ?? []).map((w, i) => {
              if (!w.start || !w.end) return null;
              const a = geo.x(ms(w.start));
              const b = geo.x(ms(w.end));
              if (b < PLOT_L || a > PLOT_R) return null; // entirely outside what was recorded
              const x0 = clampX(a);
              const x1 = Math.max(x0 + 2, clampX(b));
              const right = x0 + 150 > PLOT_R;
              return (
                <g key={i}>
                  <rect
                    className="maintenance"
                    x={x0}
                    width={x1 - x0}
                    y={M.t}
                    height={H - M.t - M.b}
                  />
                  <text
                    className="region-label"
                    x={right ? x1 - 3 : x0 + 3}
                    y={H - M.b - 5 - (i % 2) * 12}
                    textAnchor={right ? "end" : "start"}
                  >
                    Maintenance {w.id}
                  </text>
                </g>
              );
            })}
            {unexplained.map((d, i) => {
              const a = geo.x(ms(d.start));
              const b = geo.x(ms(d.end));
              if (b < PLOT_L || a > PLOT_R) return null;
              const x0 = clampX(a);
              const x1 = Math.max(x0 + 3, clampX(b));
              // the label goes inside a wide interval, otherwise beside it on whichever side has room;
              // rows alternate so neighbouring intervals do not print over each other
              const inside = x1 - x0 >= 120;
              const rightRoom = x1 + 112 <= PLOT_R;
              const lx = inside
                ? x0 + 4
                : rightRoom
                  ? x1 + 4
                  : Math.max(PLOT_L + 108, x0 - 4);
              const anchor = inside || rightRoom ? "start" : "end";
              return (
                <g
                  key={d.discrepancy_id}
                  data-testid="temperature-disagreement"
                >
                  <rect
                    className="disagree"
                    x={x0}
                    width={x1 - x0}
                    y={M.t}
                    height={H - M.t - M.b}
                  />
                  <line
                    className="disagree-edge"
                    x1={x0}
                    x2={x0}
                    y1={M.t}
                    y2={H - M.b}
                  />
                  <line
                    className="disagree-edge"
                    x1={x1}
                    x2={x1}
                    y1={M.t}
                    y2={H - M.b}
                  />
                  <text
                    className="region-label strong"
                    x={lx}
                    y={M.t + 11 + (i % 3) * 12}
                    textAnchor={anchor}
                  >
                    ⚠ Records disagree
                  </text>
                </g>
              );
            })}
            <line
              className="axis"
              x1={PLOT_L}
              x2={PLOT_R}
              y1={H - M.b}
              y2={H - M.b}
            />
            {geo.xTicks.map((t) => (
              <text
                key={t}
                className="tick"
                x={geo.x(t)}
                y={H - M.b + 14}
                textAnchor="middle"
              >
                {stamp(t)}
              </text>
            ))}
            {geo.stored.length > 1 && (
              <path className="line stored" d={geo.path(geo.stored)} />
            )}
            {geo.ref.length > 1 && (
              <path className="line ref" d={geo.path(geo.ref)} />
            )}
            {geo.stored.length === 1 && (
              <circle
                className="dot stored"
                cx={geo.x(ms(geo.stored[0].ts))}
                cy={geo.y(geo.stored[0].temp_c)}
                r={4}
              />
            )}
            {geo.ref.length === 1 && (
              <circle
                className="dot ref"
                cx={geo.x(ms(geo.ref[0].ts))}
                cy={geo.y(geo.ref[0].temp_c)}
                r={4}
              />
            )}
            {isolated.map((d) => (
              <circle
                key={d.discrepancy_id}
                className="isolated"
                data-testid="temperature-isolated"
                cx={clampX(geo.x(ms(d.start)))}
                cy={geo.y(d.reference_range_c[0])}
                r={6}
              />
            ))}
            {hx != null && (
              <g aria-hidden>
                <line
                  className="crosshair"
                  x1={hx}
                  x2={hx}
                  y1={M.t}
                  y2={H - M.b}
                />
                {hoverStored && (
                  <circle
                    className="dot stored"
                    cx={geo.x(ms(hoverStored.ts))}
                    cy={geo.y(hoverStored.temp_c)}
                    r={4}
                  />
                )}
                {hoverRef && (
                  <circle
                    className="dot ref"
                    cx={geo.x(ms(hoverRef.ts))}
                    cy={geo.y(hoverRef.temp_c)}
                    r={4}
                  />
                )}
              </g>
            )}
          </svg>
          {hx != null && at != null && (
            <div
              className={"temp-tip" + (hx > W * 0.55 ? " left" : "")}
              style={{ left: `${(hx / W) * 100}%` }}
              role="status"
              data-testid="temperature-tip"
            >
              <span className="when">{stamp(at)} UTC</span>
              {hoverRef && (
                <span data-testid="tip-reference">
                  <i className="key ref" aria-hidden />
                  <b>{hoverRef.temp_c.toFixed(1)} °C</b> reference,{" "}
                  {hhmmss(hoverRef.ts)}
                </span>
              )}
              {hoverStored && (
                <span data-testid="tip-stored">
                  <i className="key stored" aria-hidden />
                  <b>{hoverStored.temp_c.toFixed(1)} °C</b> stored,{" "}
                  {hhmmss(hoverStored.ts)}
                </span>
              )}
            </div>
          )}
        </div>
      )}
      {cut.map((s) => (
        <p
          key={s.key}
          className="small amber"
          data-testid="temperature-truncated"
        >
          {s.label}: the first {s.points.length.toLocaleString()} of{" "}
          {s.total_points.toLocaleString()} readings are drawn.
        </p>
      ))}
      {limits.map((l, i) => (
        <p key={i} className="small amber" data-testid="temperature-limit">
          {l}
        </p>
      ))}
      {notAssessable ? (
        <p className="small muted" data-testid="temperature-not-compared">
          Not compared in this evidence view, so no differences and no
          excursions are counted. That is unknown, not none.
        </p>
      ) : (
        <details
          className="temp-table"
          open={unexplained.length > 0 || isolated.length > 0}
        >
          <summary>
            Where the records differ ({all.length}) and where the reference left
            the permitted range ({(data.excursions ?? []).length})
          </summary>
          {all.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>Interval, UTC</th>
                  <th>Reference</th>
                  <th>Stored</th>
                  <th>Reading</th>
                  <th>Records</th>
                </tr>
              </thead>
              <tbody>
                {all.map((d) => (
                  <tr
                    key={d.discrepancy_id}
                    data-classification={d.classification}
                  >
                    <td>
                      {hhmmss(d.start)}
                      {d.end !== d.start && `–${hhmmss(d.end)}`}
                    </td>
                    <td>
                      {d.reference_range_c[0]} to {d.reference_range_c[1]} °C
                    </td>
                    <td>
                      {d.local_range_c[0]} to {d.local_range_c[1]} °C
                    </td>
                    <td>
                      {DISCREPANCY[d.classification] ?? words(d.classification)}
                      {d.maintenance_id ? ` (${d.maintenance_id})` : ""}
                    </td>
                    <td>
                      <Chips
                        ids={[
                          ...d.reference_event_ids.slice(0, 2),
                          ...d.local_event_ids.slice(0, 2),
                        ]}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {(data.excursions ?? []).map((e) => (
            <p key={e.excursion_id} className="small">
              The reference logger left the permitted range from{" "}
              {hhmmss(e.start)} to {hhmmss(e.end)} UTC, peaking at {e.peak_c}{" "}
              °C.{" "}
              {e.local_agrees
                ? "The stored record shows the same warming."
                : "The stored record does not show it."}{" "}
              <button
                className="linkish"
                onClick={() => open(e.reference_event_ids[0])}
              >
                Open the first reference reading
              </button>
            </p>
          ))}
        </details>
      )}
      <p className="small muted">
        {(data.limits ?? [])[0]
          ? `Limit: ${(data.limits ?? [])[0]}.`
          : "A temperature record describes the refrigerator, not who handled the record."}{" "}
        {data.produced_by}
      </p>
    </section>
  );
}

// --------------------------------------------------------------------------- second-run evaluation
