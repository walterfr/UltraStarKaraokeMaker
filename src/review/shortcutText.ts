// Mini-formato dos atalhos da legenda (ShortcutLegend.tsx), para os textos
// ficarem em uma string por grupo no i18n: itens separados por " · ", e o que
// está entre crases vira tecla (<kbd>). Testado em test/shortcutText.test.ts.

export interface ShortcutPart {
  kbd: boolean;
  text: string;
}

/** Itens de um grupo: "`Espaço` tocar · `L` próxima" -> ["`Espaço` tocar", "`L` próxima"]. */
export function shortcutItems(group: string): string[] {
  return group
    .split(" · ")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

/** Partes de um item: trechos entre crases são teclas. */
export function shortcutParts(item: string): ShortcutPart[] {
  const out: ShortcutPart[] = [];
  for (const piece of item.split(/(`[^`]+`)/)) {
    if (piece.length === 0) continue;
    const isKey = piece.length > 2 && piece.startsWith("`") && piece.endsWith("`");
    out.push({ kbd: isKey, text: isKey ? piece.slice(1, -1) : piece });
  }
  return out;
}
