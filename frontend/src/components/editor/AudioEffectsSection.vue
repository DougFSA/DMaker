<script setup lang="ts">
/* O bloco "Efeitos de áudio" do painel Filtros: a cadeia de efeitos do item selecionado na linha do tempo (ou a do
   master, sem seleção), na ordem em que o som passa por ela. O menu "+ Efeito" e o formulário de cada efeito saem do
   catálogo do servidor. Cada ação (adicionar, remover, mover, ligar, mudar um valor) é um passo do desfazer. */
import { computed, onMounted, ref } from 'vue'
import { PopoverContent, PopoverPortal, PopoverRoot, PopoverTrigger } from 'reka-ui'
import type { AudioEffectInfo } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import {
  addEffectIn,
  chainOf,
  effectContextFor,
  effectsFor,
  moveEffectIn,
  newEffect,
  removeEffectIn,
  setEnabledIn,
  targetMayGrow,
} from '@/lib/audioEffects'
import { stableKey } from '@/lib/editorSpec'
import { useAudioEffectsStore } from '@/stores/audioEffects'
import { useEditorStore } from '@/stores/editor'
import AudioEffectCard from './AudioEffectCard.vue'

const editor = useEditorStore()
const catalog = useAudioEffectsStore()

onMounted(() => void catalog.load())

/** O item de que os efeitos falam: o último que a pessoa selecionou, como no resto do painel Filtros. */
const primary = computed(() => {
  const last = editor.selection[editor.selection.length - 1]
  return last ? editor.findItem(last) : null
})
const context = computed(() => effectContextFor(primary.value, editor.view))
const chain = computed(() => (context.value.kind === 'chain' ? context.value.chain : null))
const effects = computed(() => (chain.value ? chainOf(editor.spec, chain.value.listPath) : []))

const mayGrow = computed(() => !!chain.value && targetMayGrow(catalog.targets, chain.value.targetKey))
const offered = computed(() => effectsFor(catalog.effects, mayGrow.value))
/** O que o menu esconde neste lugar (o Repetir fora da voz gravada e da música), para explicar a ausência. */
const hidden = computed(() => catalog.effects.filter((info) => !offered.value.includes(info)))
const growableLabels = computed(() => catalog.targets.filter((target) => target.may_grow).map((target) => target.label))

const menuOpen = ref(false)

/** A cadeia em edição na hora da ação; as ações pedem antes a digitação que ainda espera, para ela não se perder. */
function act(change: (draft: Record<string, unknown>, listPath: string) => unknown): void {
  const current = chain.value
  if (!current) return
  editor.flushPendingEdits()
  editor.mutate((draft) => change(draft, current.listPath))
}

function add(info: AudioEffectInfo): void {
  act((draft, listPath) => addEffectIn(draft, listPath, newEffect(info)))
  menuOpen.value = false
}

const remove = (index: number) => act((draft, listPath) => removeEffectIn(draft, listPath, index))
const toggle = (index: number, enabled: boolean) => act((draft, listPath) => setEnabledIn(draft, listPath, index, enabled))
const moveTo = (from: number, to: number) => act((draft, listPath) => moveEffectIn(draft, listPath, from, to))

/* ---------- arrastar para reordenar ---------- */

const dragFrom = ref<number | null>(null)
const dropAt = ref<number | null>(null)

/* só o arraste que saiu de uma alça daqui é aceito: arquivo ou painel vindo de fora segue para quem o trata */
function onDragOver(index: number, event: DragEvent): void {
  if (dragFrom.value === null) return
  event.preventDefault()
  dropAt.value = index
}

function onDrop(index: number, event: DragEvent): void {
  const from = dragFrom.value
  if (from === null) return
  event.preventDefault()
  endDrag()
  moveTo(from, index)
}

function endDrag(): void {
  dragFrom.value = null
  dropAt.value = null
}
</script>

<template>
  <section class="effects" aria-label="Efeitos de áudio" data-audio-effects>
    <header class="effects__head">
      <div class="effects__heading">
        <h4 class="effects__title">Efeitos de áudio</h4>
        <p v-if="chain" class="effects__target" data-effects-target>{{ chain.title }}</p>
      </div>
      <PopoverRoot v-model:open="menuOpen">
        <PopoverTrigger as-child>
          <AppButton
            size="sm"
            :disabled="!chain || !catalog.loaded"
            aria-label="Adicionar efeito de áudio"
            title="Adicionar um efeito de áudio ao fim da cadeia"
            data-effects-add
          >
            <AppIcon name="plus" :size="16" />
            Efeito
          </AppButton>
        </PopoverTrigger>
        <PopoverPortal>
          <PopoverContent class="effects-menu" align="end" :side-offset="6" aria-label="Efeitos de áudio disponíveis">
            <ul v-if="offered.length > 0" class="effects-menu__list">
              <li v-for="info in offered" :key="info.type">
                <button type="button" class="effects-menu__item" :data-add-effect="info.type" :title="info.summary" @click="add(info)">
                  <span class="effects-menu__name">{{ info.label }}</span>
                  <span v-if="info.audacity_name !== info.label" class="effects-menu__audacity">{{ info.audacity_name }}</span>
                </button>
              </li>
            </ul>
            <p v-else class="effects-menu__note">Nenhum efeito disponível.</p>
            <p v-if="hidden.length > 0 && offered.length > 0" class="effects-menu__note" data-effects-hidden>
              {{ hidden.map((info) => info.label).join(', ') }}: só vale em {{ growableLabels.join(' e ').toLowerCase() }}.
            </p>
          </PopoverContent>
        </PopoverPortal>
      </PopoverRoot>
    </header>

    <p v-if="!chain" class="effects__note" data-effects-silent>
      O item selecionado não tem som, então não recebe efeitos de áudio. Sem nada selecionado, o painel edita o master (a mistura inteira).
    </p>
    <template v-else>
      <p v-if="!catalog.loaded && catalog.error" class="effects__note effects__note--warning" role="status" data-effects-error>
        Não foi possível carregar o catálogo de efeitos de áudio: {{ catalog.error }}
        <AppButton size="sm" variant="ghost" @click="catalog.load()">Tentar de novo</AppButton>
      </p>
      <p v-if="effects.length === 0" class="effects__note" data-effects-empty>
        Nenhum efeito neste item. Use o botão Efeito para adicionar.
      </p>
      <ul v-else class="effects__list" aria-label="Cadeia de efeitos, na ordem em que o som passa por eles">
        <AudioEffectCard
          v-for="(effect, index) in effects"
          :key="`${chain.listPath}:${stableKey(effect)}`"
          :effect="effect"
          :info="catalog.infoOf(effect.type)"
          :start-param="catalog.commonParam('start')"
          :end-param="catalog.commonParam('end')"
          :index="index"
          :count="effects.length"
          :list-path="chain.listPath"
          :dragging="dragFrom === index"
          :drop-target="dropAt === index && dragFrom !== index"
          @toggle="toggle(index, $event)"
          @remove="remove(index)"
          @move="moveTo(index, index + $event)"
          @drag-start="dragFrom = index"
          @drag-end="endDrag"
          @drag-over="onDragOver(index, $event)"
          @drop="onDrop(index, $event)"
        />
      </ul>
    </template>
  </section>
</template>

<style scoped>
.effects {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.effects__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2) var(--space-3);
}

.effects__heading {
  flex: 1 1 8rem;
  min-width: 0;
}

.effects__title {
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.effects__target {
  overflow: hidden;
  font-size: var(--text-sm);
  color: var(--color-text-soft);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.effects__note {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.effects__note--warning {
  color: var(--color-warning);
}

.effects__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}
</style>

<style>
.effects-menu {
  z-index: 70;
  min-width: 13rem;
  max-width: 18rem;
  max-height: min(24rem, calc(100vh - 6rem));
  overflow-y: auto;
  padding: var(--space-2);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
}

.effects-menu:focus {
  outline: none;
}

.effects-menu__list {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}

.effects-menu__item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  font-size: var(--text-sm);
  text-align: left;
  color: var(--color-text);
}

.effects-menu__item:hover,
.effects-menu__item:focus-visible {
  background: var(--color-surface-hover);
}

.effects-menu__audacity {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.effects-menu__note {
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}
</style>
