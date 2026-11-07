// Lógica pura do sing-along (rastro de pitch do microfone na revisão).
// Separada do ReviewScreen pra ser testável com `npm test`, sem React nem DOM.

export interface MicSample {
  t: number; // segundo da música (audio.currentTime)
  pitch: number; // semitons UltraStar (0 == C4)
}

// Quanto do passado o rastro mantém.
export const MIC_TRAIL_S = 5;
// Clareza mínima do pitchy: abaixo disso é silêncio/ruído, não vira ponto.
export const MIC_CLARITY_MIN = 0.9;
// Faixa de voz cantada (~D2 a ~D6). Fora disso é ruído de sala ou harmônico.
export const MIC_HZ_MIN = 70;
export const MIC_HZ_MAX = 1200;
// Intervalo sem amostra a partir do qual o rastro NÃO liga os pontos - ligar
// atravessando uma pausa desenharia uma reta falsa entre duas notas.
export const MIC_GAP_S = 0.15;

// Mesma fórmula do pitch.py: pitch 0 == C4 == MIDI 60.
export function hzToUltrastarPitch(hz: number): number {
  return 69 + 12 * Math.log2(hz / 440) - 60;
}

// Acrescenta uma leitura do detector ao rastro (muta `trail`) e descarta o que
// saiu da janela. Leituras fracas ou fora da voz não entram, mas a limpeza
// roda sempre.
export function pushMicSample(
  trail: MicSample[],
  hz: number,
  clarity: number,
  t: number,
): void {
  // Música voltou no tempo (usuário clicou mais atrás): o rastro antigo é do
  // "futuro" agora e quebraria o traçado.
  if (trail.length > 0 && trail[trail.length - 1].t > t) trail.length = 0;

  if (clarity >= MIC_CLARITY_MIN && hz >= MIC_HZ_MIN && hz <= MIC_HZ_MAX) {
    trail.push({ t, pitch: hzToUltrastarPitch(hz) });
  }

  const cutoff = t - MIC_TRAIL_S;
  let drop = 0;
  while (drop < trail.length && trail[drop].t < cutoff) drop++;
  if (drop > 0) trail.splice(0, drop);
}
