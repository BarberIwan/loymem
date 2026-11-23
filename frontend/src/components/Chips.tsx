import s from "./chips.module.css";

/** A row of toggles for a bitmask, e.g. days of the week. */
export function MaskChips({ labels, value, onChange, label }: { labels: string[]; value: number; onChange: (v: number) => void; label: string }) {
  return (
    <div className={s.chips} role="group" aria-label={label}>
      {labels.map((l, i) => {
        const on = (value & (1 << i)) !== 0;
        return (
          <button
            key={l}
            type="button"
            className={s.chip}
            aria-pressed={on}
            onClick={() => {
              const next = value ^ (1 << i);
              if (next !== 0) onChange(next);
            }}
          >
            {l}
          </button>
        );
      })}
    </div>
  );
}
