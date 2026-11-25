import { useState } from "react";
import { shortcutItems, shortcutParts } from "./shortcutText";

// Atalhos da Revisão, agrupados e recolhíveis (antes era uma linha corrida).
// Aberto ou fechado fica lembrado entre sessões.

const OPEN_KEY = "uskmaker-review-shortcuts-open";

function readOpen(): boolean {
  try {
    return localStorage.getItem(OPEN_KEY) === "1";
  } catch {
    return false;
  }
}

interface Props {
  summary: string;
  groups: { title: string; items: string }[];
}

export default function ShortcutLegend({ summary, groups }: Props) {
  const [open, setOpen] = useState(readOpen);
  return (
    <details
      className="review-shortcuts"
      open={open}
      onToggle={(e) => {
        const now = e.currentTarget.open;
        setOpen(now);
        try {
          localStorage.setItem(OPEN_KEY, now ? "1" : "0");
        } catch {
          /* sem armazenamento: só não lembra */
        }
      }}
    >
      <summary>{summary}</summary>
      <div className="shortcut-grid">
        {groups.map((g) => (
          <div key={g.title} className="shortcut-group">
            <div className="shortcut-group-title">{g.title}</div>
            <ul>
              {shortcutItems(g.items).map((item) => (
                <li key={item}>
                  {shortcutParts(item).map((p, i) => (p.kbd ? <kbd key={i}>{p.text}</kbd> : <span key={i}>{p.text}</span>))}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </details>
  );
}
