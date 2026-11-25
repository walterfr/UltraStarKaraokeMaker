import { useCallback, useEffect, useMemo, useRef } from "react";
import { keyAt, pianoLayout } from "./pianoLayout";

// Teclado horizontal da Revisão: acende as teclas apertadas (teclado MIDI ou
// mouse) e toca com o mouse - clicar toca, arrastar faz glissando. Os eventos
// de ponteiro ficam no contêiner e a tecla sai de keyAt (pianoLayout.ts):
// assim o arraste atravessa teclas e a preta tem prioridade na parte de cima,
// como num piano de verdade.

const BLACK_HEIGHT = 0.62; // fração da altura ocupada pelas pretas

interface Props {
  /** MIDI da primeira e da última tecla (pontas pretas viram brancas) */
  low: number;
  high: number;
  /** notas MIDI acesas agora */
  pressed: ReadonlySet<number>;
  onPress: (midi: number) => void;
  onRelease: (midi: number) => void;
  title?: string;
}

export default function PianoKeyboard({ low, high, pressed, onPress, onRelease, title }: Props) {
  const keys = useMemo(() => pianoLayout(low, high), [low, high]);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const mouseNoteRef = useRef<number | null>(null);
  // callbacks atuais sem reinstalar os listeners de janela a cada render
  // (reinstalar soltaria a nota segurada no meio do toque)
  const onPressRef = useRef(onPress);
  const onReleaseRef = useRef(onRelease);
  onPressRef.current = onPress;
  onReleaseRef.current = onRelease;

  const releaseMouse = useCallback(() => {
    const n = mouseNoteRef.current;
    if (n === null) return;
    mouseNoteRef.current = null;
    onReleaseRef.current(n);
  }, []);

  // soltar o botão fora do teclado (ou a janela perder o foco) também solta a nota
  useEffect(() => {
    window.addEventListener("pointerup", releaseMouse);
    window.addEventListener("blur", releaseMouse);
    return () => {
      window.removeEventListener("pointerup", releaseMouse);
      window.removeEventListener("blur", releaseMouse);
      releaseMouse();
    };
  }, [releaseMouse]);

  const noteAt = (e: React.PointerEvent): number | null => {
    const box = boxRef.current;
    if (!box) return null;
    const r = box.getBoundingClientRect();
    const k = keyAt(keys, (e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height, BLACK_HEIGHT);
    return k ? k.midi : null;
  };

  const press = (n: number) => {
    releaseMouse();
    mouseNoteRef.current = n;
    onPressRef.current(n);
  };

  return (
    <div
      ref={boxRef}
      className="h-piano"
      title={title}
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        const n = noteAt(e);
        if (n !== null) press(n);
      }}
      onPointerMove={(e) => {
        if (mouseNoteRef.current === null || !(e.buttons & 1)) return;
        const n = noteAt(e);
        if (n !== null && n !== mouseNoteRef.current) press(n);
      }}
      onPointerLeave={releaseMouse}
      onContextMenu={(e) => e.preventDefault()}
    >
      {keys
        .filter((k) => !k.black)
        .map((k) => (
          <div
            key={k.midi}
            className={`h-piano-key white${pressed.has(k.midi) ? " lit" : ""}${k.midi % 12 === 0 ? " c" : ""}`}
            style={{ left: `${k.left * 100}%`, width: `${k.width * 100}%` }}
            title={`${k.name} (${k.midi - 60})`}
          >
            <span>{k.name}</span>
          </div>
        ))}
      {keys
        .filter((k) => k.black)
        .map((k) => (
          <div
            key={k.midi}
            className={`h-piano-key black${pressed.has(k.midi) ? " lit" : ""}`}
            style={{ left: `${k.left * 100}%`, width: `${k.width * 100}%`, height: `${BLACK_HEIGHT * 100}%` }}
            title={`${k.name} (${k.midi - 60})`}
          />
        ))}
    </div>
  );
}
