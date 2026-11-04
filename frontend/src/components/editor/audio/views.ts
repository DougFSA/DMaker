/* Os pontos de extensão do painel Áudio. O painel não conhece nenhuma vista nem nenhum botão extra pelo nome: ele percorre
   estas listas.

   - **Vista nova** (o espectrograma do DMK-63): acrescente uma entrada em `AUDIO_VIEWS` com o componente dela. O painel
     mostra um seletor "Vista" quando há mais de uma, e o componente recebe a mesma `data` (a resposta da onda) e emite os
     mesmos eventos (`size` com a largura em pixels, `scrub` e `scrub-end`) que a vista da onda. Ele lê o resto, a janela
     de tempo, a seleção, o cursor e a posição de reprodução, do `useAudioPanelStore`, então as vistas dividem o mesmo
     eixo, e arrastar uma seleção numa delas a seleciona nas outras.
   - **Ferramenta ou comando novo** (a gravação do DMK-65): acrescente o componente a `AUDIO_TOOLBAR_EXTRAS`; ele aparece no
     fim da barra de reprodução e usa o store do painel e a `editor.applyOp` como qualquer comando. Uma ferramenta que
     precisa do mouse sobre a onda entra também em `PanelTool` (`stores/audioPanel.ts`) e no `onAreaDown` da vista. */
import type { Component } from 'vue'
import AudioWaveView from './AudioWaveView.vue'

export interface AudioViewDef {
  id: string
  title: string
  component: Component
}

export interface AudioToolbarExtra {
  id: string
  component: Component
}

/** As vistas do painel; a primeira é a padrão. */
export const AUDIO_VIEWS: AudioViewDef[] = [{ id: 'wave', title: 'Onda', component: AudioWaveView }]

/** Os botões e controles a mais da barra de reprodução, na ordem. */
export const AUDIO_TOOLBAR_EXTRAS: AudioToolbarExtra[] = []
