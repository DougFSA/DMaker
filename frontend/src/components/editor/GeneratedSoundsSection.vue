<script setup lang="ts">
/* O bloco "Sons gerados" do painel Filtros: os sons sintetizados do projeto (`audio.generated`: tom, ruído, bipe, metrônomo...),
   cada um um cartão com os parâmetros do gerador, o instante, a duração e o volume. O menu "Gerar som" lista os geradores
   do catálogo do servidor por família, então um gerador novo aparece aqui sem mexer neste arquivo. Os sons moram na spec,
   seguem o desfazer e o Salvar do editor, e aparecem na trilha SFX da linha do tempo, onde se arrastam. A cadeia de efeitos
   de cada um é a do painel "Efeitos de áudio", com o som gerado selecionado na linha do tempo. */
import { computed, onMounted, ref } from 'vue'
import { PopoverContent, PopoverPortal, PopoverRoot, PopoverTrigger } from 'reka-ui'
import type { AudioEffectParam } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import {
  GENERATED_PATH,
  GENERATED_TRACK,
  MAX_SOUND_SECONDS,
  MIN_SOUND_SECONDS,
  addGeneratedIn,
  generatedList,
  groupByFamily,
  newSound,
  removeGeneratedIn,
  soundParamValue,
} from '@/lib/generatedSounds'
import { useAudioGeneratorsStore } from '@/stores/audioGenerators'
import { useEditorStore } from '@/stores/editor'
import SoundField from './SoundField.vue'

const editor = useEditorStore()
const catalog = useAudioGeneratorsStore()

onMounted(() => {
  catalog.load().catch(() => undefined)
})

const sounds = computed(() => generatedList(editor.spec))
const families = computed(() => groupByFamily(catalog.generators))
const menuOpen = ref(false)

/** O som que a linha do tempo tem selecionado (a trilha SFX), para o cartão dele ficar destacado. */
const selectedIndex = computed(() => {
  const last = editor.selection[editor.selection.length - 1]
  const found = last ? editor.findItem(last) : null
  return found && found.trackId === GENERATED_TRACK ? found.item.index : null
})

/** Os campos do item, que todo gerador tem; o servidor recusa o que passar da faixa. */
const ITEM_FIELDS: Array<Pick<AudioEffectParam, 'name' | 'label' | 'kind' | 'unit' | 'hint' | 'minimum' | 'maximum' | 'options' | 'default'>> = [
  { name: 'start', default: 0, label: 'Início', kind: 'number', unit: 's', hint: 'O instante do vídeo final em que o som começa.', minimum: 0, maximum: null, options: [] },
  { name: 'duration', default: 1, label: 'Duração', kind: 'number', unit: 's', hint: 'Quanto o som dura.', minimum: MIN_SOUND_SECONDS, maximum: MAX_SOUND_SECONDS, options: [] },
  { name: 'volume', default: 1, label: 'Volume', kind: 'number', unit: '', hint: 'Ganho linear do item (1 é o nível do gerador).', minimum: 0, maximum: 4, options: [] },
  { name: 'pan', default: 0, label: 'Equilíbrio', kind: 'number', unit: '', hint: 'De -1 (esquerda) a 1 (direita).', minimum: -1, maximum: 1, options: [] },
]
const ITEM_DEFAULTS: Record<string, number> = { start: 0, duration: 1, volume: 1, pan: 0 }

function itemValue(index: number, name: string): number {
  const stored = (sounds.value[index] as unknown as Record<string, unknown>)[name]
  return typeof stored === 'number' ? stored : (ITEM_DEFAULTS[name] ?? 0)
}

const infoOf = (generator: string) => catalog.infoOf(generator)

/** Acrescenta o som no instante do cursor, com a duração que o gerador pede, e o seleciona na linha do tempo. */
function add(type: string): void {
  const info = catalog.infoOf(type)
  if (!info) return
  menuOpen.value = false
  editor.flushPendingEdits()
  editor.mutate((draft) => addGeneratedIn(draft, newSound(info, editor.playhead ?? 0)))
}

function remove(index: number): void {
  editor.flushPendingEdits()
  editor.mutate((draft) => removeGeneratedIn(draft, index))
}
</script>

<template>
  <section class="sounds" aria-label="Sons gerados" data-generated-sounds>
    <header class="sounds__head">
      <div class="sounds__heading">
        <h4 class="sounds__title">Sons gerados</h4>
        <p class="sounds__hint">Tom, ruído, bipe, metrônomo: entram na trilha SFX e não abaixam a música.</p>
      </div>
      <PopoverRoot v-model:open="menuOpen">
        <PopoverTrigger as-child>
          <AppButton size="sm" :disabled="!catalog.loaded" title="Gerar um som novo no cursor" data-generated-add>
            <AppIcon name="plus" :size="16" />
            Gerar som
          </AppButton>
        </PopoverTrigger>
        <PopoverPortal>
          <PopoverContent class="sounds-menu" align="end" :side-offset="6" aria-label="Geradores de som">
            <div v-for="group in families" :key="group.family" class="sounds-menu__group">
              <p class="sounds-menu__family">{{ group.label }}</p>
              <button
                v-for="info in group.items"
                :key="info.type"
                type="button"
                class="sounds-menu__item"
                :title="info.summary"
                :data-add-generator="info.type"
                @click="add(info.type)"
              >
                {{ info.label }}
              </button>
            </div>
          </PopoverContent>
        </PopoverPortal>
      </PopoverRoot>
    </header>

    <p v-if="catalog.error" class="sounds__note" role="status">O catálogo dos geradores não carregou: {{ catalog.error }}</p>
    <p v-else-if="sounds.length === 0" class="sounds__empty">Nenhum som gerado. Use o botão Gerar som.</p>

    <article
      v-for="(sound, index) in sounds"
      :key="index"
      class="sound"
      :class="{ 'sound--selected': selectedIndex === index }"
      :data-generated-sound="index"
    >
      <header class="sound__head">
        <h5 class="sound__title">{{ infoOf(sound.generator)?.label ?? sound.generator }}</h5>
        <AppButton size="sm" icon-only :aria-label="`Remover o som gerado ${index + 1}`" title="Remover este som" @click="remove(index)">
          <AppIcon name="x" :size="14" />
        </AppButton>
      </header>
      <div class="sound__fields">
        <SoundField
          v-for="field in ITEM_FIELDS"
          :key="field.name"
          :param="field"
          :value="itemValue(index, field.name)"
          :path="`${GENERATED_PATH}.${index}.${field.name}`"
        />
        <template v-if="infoOf(sound.generator)">
          <SoundField
            v-for="param in infoOf(sound.generator)!.parameters"
            :key="`${sound.generator}.${param.name}`"
            :param="param"
            :value="soundParamValue(sound, param)"
            :path="`${GENERATED_PATH}.${index}.params.${param.name}`"
          />
        </template>
      </div>
    </article>
  </section>
</template>

<style scoped>
.sounds {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.sounds__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2) var(--space-3);
}

.sounds__heading {
  flex: 1 1 8rem;
  min-width: 0;
}

.sounds__title {
  margin: 0;
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.sounds__hint,
.sounds__empty,
.sounds__note {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.sounds__note {
  color: var(--color-warning);
}

.sound {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.sound--selected {
  border-color: var(--color-accent, var(--color-border-strong));
}

.sound__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sound__title {
  margin: 0;
  font-size: var(--text-sm);
}

.sound__fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}
</style>

<style>
.sounds-menu {
  z-index: 70;
  min-width: 12rem;
  max-height: min(24rem, calc(100vh - 6rem));
  overflow-y: auto;
  padding: var(--space-2);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
}

.sounds-menu:focus {
  outline: none;
}

.sounds-menu__family {
  margin: var(--space-2) var(--space-3) 0;
  font-size: var(--text-xs);
  color: var(--color-text-soft);
  text-transform: uppercase;
}

.sounds-menu__item {
  display: block;
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  font-size: var(--text-sm);
  text-align: left;
  color: var(--color-text);
}

.sounds-menu__item:hover,
.sounds-menu__item:focus-visible {
  background: var(--color-surface-hover);
}
</style>
