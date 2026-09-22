import { useState, type FormEvent } from "react";
import { fmtSeconds, fmtUsd, type Budget, type Estimate, type EstimateLine } from "../api";

function what(l: EstimateLine): string {
  if (!l.todo) return `all ${l.steps} made`;
  const todo = l.todo === l.steps ? `${l.todo} to make` : `${l.todo} of ${l.steps} to make`;
  if (!l.paid_seconds || l.local) return todo;
  const trimmed = l.waste_seconds ? `, ${fmtSeconds(l.waste_seconds)} of it trimmed` : "";
  return `${todo}, ${fmtSeconds(l.paid_seconds)} billed${trimmed}`;
}

function cost(l: EstimateLine): string {
  if (!l.todo) return "nothing";
  if (l.local) return l.gpu_seconds ? `free, about ${fmtSeconds(l.gpu_seconds)} of GPU` : "free";
  return fmtUsd(l.cost_usd);
}

function BudgetForm({ budget, busy, onBudget }: Props) {
  const [editing, setEditing] = useState(false);
  const [usd, setUsd] = useState(String(budget.usd));

  function save(e: FormEvent) {
    e.preventDefault();
    const value = Number(usd);
    if (Number.isFinite(value) && value >= 0) {
      onBudget(value);
      setEditing(false);
    }
  }

  if (!editing)
    return (
      <div className="row">
        <span>
          Budget {budget.usd ? fmtUsd(budget.usd) : "$0"}{" "}
          {budget.default ? "(the default from Settings)" : "for this story"}
          {budget.spent_usd ? `, ${fmtUsd(budget.spent_usd)} spent so far` : ", nothing spent yet"}.
        </span>
        <button
          type="button"
          className="quiet small"
          disabled={busy}
          onClick={() => {
            setUsd(String(budget.usd));
            setEditing(true);
          }}
        >
          Change
        </button>
        {!budget.default && (
          <button type="button" className="quiet small" onClick={() => onBudget(null)} disabled={busy}>
            Follow Settings
          </button>
        )}
      </div>
    );
  return (
    <form className="row" onSubmit={save}>
      <label className="row" htmlFor="budget-usd">
        Budget for this story, in dollars
      </label>
      <input
        id="budget-usd"
        type="number"
        min={0}
        step={0.5}
        value={usd}
        onChange={(e) => setUsd(e.target.value)}
        style={{ width: 110 }}
      />
      <button type="submit" className="small primary" disabled={busy}>
        Save
      </button>
      <button type="button" className="small" onClick={() => setEditing(false)}>
        Keep it
      </button>
    </form>
  );
}

interface Props {
  budget: Budget;
  busy: boolean;
  onBudget: (usd: number | null) => void;
}

/** What rendering would cost now, stage by stage, and the story's budget. */
export default function EstimateBox({
  estimate,
  error,
  ...budget
}: Props & { estimate: Estimate | null; error: string | null }) {
  if (!estimate) return <p className="muted">{error ?? "Working out what it costs…"}</p>;
  return (
    <section className="panel estimate" aria-label="What it costs">
      <h2>What it costs</h2>
      <dl>
        {estimate.lines.map((l) => (
          <div key={l.stage}>
            <dt>{l.label}</dt>
            <dd>
              {l.model_label} · {what(l)}
            </dd>
            <dd className="cost">{cost(l)}</dd>
          </div>
        ))}
        <div className="total">
          <dt>All of it</dt>
          <dd>
            {estimate.waste_seconds
              ? `${fmtSeconds(estimate.waste_seconds)} of video billed and trimmed`
              : ""}
          </dd>
          <dd className="cost">{fmtUsd(estimate.total_usd)}</dd>
        </div>
      </dl>
      {!!estimate.short_usd && (
        <p className="error">
          This needs {fmtUsd(estimate.short_usd)} more than the budget allows. It stops before the stage that
          would go over, so raise the budget to carry on.
        </p>
      )}
      <small className="muted">
        {estimate.price_date &&
          `List prices from ${new Date(`${estimate.price_date}T12:00`).toLocaleDateString(undefined, { dateStyle: "medium" })}. `}
        {!estimate.measured && "Scene lengths are guessed from the words until the narration is recorded."}
      </small>
      <BudgetForm {...budget} />
    </section>
  );
}
