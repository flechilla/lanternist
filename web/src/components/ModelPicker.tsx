import { useState } from "react";
import { Link } from "react-router-dom";
import { chosenModel, priceOf, type MediaCatalog, type MediaModel } from "../api";

function Row({ m, chosen, onPick }: { m: MediaModel; chosen: boolean; onPick: () => void }) {
  const cheapest = m.quality?.options.reduce<number | null>(
    (lo, o) => (o.usd != null && (lo == null || o.usd < lo) ? o.usd : lo),
    null,
  );
  const price =
    m.quality && cheapest != null && m.quality.options.length > 1
      ? `from ${priceOf({ usd: cheapest, gpu_seconds: null }, m.per)}`
      : priceOf(m, m.per);
  return (
    <button type="button" className="pick-row" aria-pressed={chosen} disabled={!m.available} onClick={onPick}>
      <b>{m.label}</b>
      <small>
        {price}
        {m.commercial_use === false ? " · personal use only" : ""}
      </small>
    </button>
  );
}

/** Choose the model a story uses for one stage, and its quality where it offers one. */
export default function ModelPicker({
  label,
  catalog,
  error,
  value,
  quality,
  disabled,
  allowDefault = true,
  off,
  onChange,
}: {
  label: string;
  catalog: MediaCatalog | null;
  error: string | null;
  /** The story's choice; empty means the default from Settings. */
  value: string;
  /** The chosen quality; leave it out where there's no quality to choose (Settings). */
  quality?: string | null;
  disabled?: boolean;
  /** Offer "the default" as a choice: yes for a story, no in Settings, where the default is chosen. */
  allowDefault?: boolean;
  /** Offer turning the stage off (the value "none"), described by this text. */
  off?: string;
  onChange: (model: string, quality: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const isOff = value === "none" || (!value && catalog?.default === "none");
  const { model, qualityId, price } = chosenModel(catalog, isOff ? "" : value, quality ?? null);
  const models = (catalog?.models ?? []).filter((m) => m.status !== "deprecated" || m.id === model?.id);
  const local = models.filter((m) => m.local);
  const remote = models.filter((m) => !m.local);
  const byDefault = catalog?.models.find((m) => m.id === catalog.default);

  function pick(id: string) {
    const next = catalog?.models.find((m) => m.id === (id || catalog.default));
    // A quality carries over to the new model when it offers the same one.
    onChange(id, next?.quality?.options.some((o) => o.id === qualityId) ? qualityId : null);
    setOpen(false);
  }

  return (
    <div className="field">
      <span>{label}</span>
      <div className="pick">
        <div className="what">
          <b>
            {isOff ? "Off" : (model?.label ?? (value || "…"))}
            {allowDefault && !value && (model || isOff) ? " (the default)" : ""}
          </b>
          <small>{isOff ? off : model ? priceOf(price, model.per) : (error ?? "Loading the models…")}</small>
        </div>
        <button
          type="button"
          className="small"
          aria-expanded={open}
          disabled={disabled}
          onClick={() => setOpen(!open)}
        >
          {open ? "Close" : "Change"}
        </button>
      </div>
      {model?.quality && quality !== undefined && !isOff && (
        <div className="segmented" role="group" aria-label={`${label}: quality`}>
          {model.quality.options.map((o) => (
            <button
              key={o.id}
              type="button"
              aria-pressed={o.id === qualityId}
              disabled={disabled}
              title={priceOf(o, model.per)}
              onClick={() => onChange(value || model.id, o.id)}
            >
              {o.label}
            </button>
          ))}
        </div>
      )}
      {model?.notes && !isOff && <small>{model.notes}</small>}
      {open && catalog && (
        <div className="pick-menu">
          <div className="pick-list">
            {allowDefault && byDefault && (
              <button type="button" className="pick-row" aria-pressed={!value} onClick={() => pick("")}>
                <b>The default: {byDefault.label}</b>
                <small>Follows what Settings says for every story.</small>
              </button>
            )}
            {off && (
              <button
                type="button"
                className="pick-row"
                aria-pressed={value === "none"}
                onClick={() => pick("none")}
              >
                <b>Off</b>
                <small>{off}</small>
              </button>
            )}
            {local.length > 0 && <p className="group">On this machine</p>}
            {local.map((m) => (
              <Row key={m.id} m={m} chosen={value === m.id} onPick={() => pick(m.id)} />
            ))}
            {remote.length > 0 && <p className="group">fal.ai</p>}
            {remote.some((m) => !m.available) && (
              <small className="muted">
                Add a fal key in <Link to="/settings">Settings</Link> to use these.
              </small>
            )}
            {remote.map((m) => (
              <Row key={m.id} m={m} chosen={value === m.id} onPick={() => pick(m.id)} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
