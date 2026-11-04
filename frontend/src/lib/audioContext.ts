/* O contexto de áudio do navegador, entregue ao motor de reprodução e ao antes e depois pela interface mínima que eles
   usam (`WavAudioContext`). Fica separado para os dois criarem o contexto do mesmo jeito, e só depois de um gesto da
   pessoa: o navegador não deixa um áudio começar sozinho. */
import type { WavAudioContext } from './audioPlayback'

export function newAudioContext(): WavAudioContext {
  const Constructor =
    window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!Constructor) throw new Error('Este navegador não tem Web Audio.')
  return new Constructor() as unknown as WavAudioContext
}
