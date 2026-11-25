// Testes do src/review/shortcutText.ts (formato dos atalhos da legenda) -
// rodar com `npm test`.
import { test } from "node:test";
import assert from "node:assert/strict";
import { shortcutItems, shortcutParts } from "../src/review/shortcutText.ts";

test("itens separados por ' · ', sem vazios", () => {
  assert.deepEqual(shortcutItems("`Espaço` tocar · `L` próxima linha ·  "), ["`Espaço` tocar", "`L` próxima linha"]);
});

test("trechos entre crases viram teclas, o resto é texto", () => {
  assert.deepEqual(shortcutParts("`Ctrl+C` `Ctrl+V` copiar/colar"), [
    { kbd: true, text: "Ctrl+C" },
    { kbd: false, text: " " },
    { kbd: true, text: "Ctrl+V" },
    { kbd: false, text: " copiar/colar" },
  ]);
  assert.deepEqual(shortcutParts("roda: rolar"), [{ kbd: false, text: "roda: rolar" }]);
  assert.deepEqual(shortcutParts("``"), [{ kbd: false, text: "``" }]); // crase vazia não é tecla
});
