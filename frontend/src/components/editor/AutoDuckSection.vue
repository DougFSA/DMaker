<script setup lang="ts">
/* O bloco "Abaixar sob outra trilha (Auto Duck)" do painel Filtros: aparece quando o item selecionado é de uma trilha de
   áudio que pode ser o fundo (o som dos clipes, uma faixa externa, a música, a narração ou a voz gravada). Cada regra diz
   qual outra trilha comanda: o fundo abaixa enquanto ela fala. As regras moram em `audio.ducks`, seguem o desfazer e o
   Salvar do editor como o resto, e a lista de trilhas que podem comandar é só a que o servidor aceita. */
import { computed } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import AppNumberInput from '@/components/ui/AppNumberInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import {
  DUCKS_PATH,
  DUCK_FIELDS,
  addRuleIn,
  clampDuck,
  duckValue,
  isDuckTrack,
  isExternalTrack,
  keyOptions,
  removeRuleIn,
  rulesFor,
  type DuckFieldName,
} from '@/lib/autoDuck'
import { useEditorStore } from '@/stores/editor'

const editor = useEditorStore()

/** A trilha do último item selecionado, se ela pode ser o fundo de uma regra. */
const background = computed(() => {
  const last = editor.selection[editor.selection.length - 1]
  const selected = last ? editor.findItem(last) : null
  return selected && isDuckTrack(selected.trackId) ? selected.trackId : null
})

/** As trilhas de áudio que existem neste projeto, na ordem da linha do tempo. */
const present = computed(() => (editor.view?.tracks ?? []).map((track) => track.id).filter(isDuckTrack))
const rules = computed(() => (background.value ? rulesFor(editor.spec, background.value) : []))
const candidates = computed(() => (background.value ? keyOptions(background.value, present.value) : []))

const names: Record<string, string> = { A1: 'Som dos clipes (A1)', MUS: 'Música (MUS)', NAR: 'Narração (NAR)', VO: 'Voz gravada (VO)', SFX: 'Sons gerados (SFX)' }
const nameOf = (id: string) => names[id] ?? (isExternalTrack(id) ? `Faixa externa (${id})` : id)

const reason = computed(() => {
  const id = background.value
  if (!id || candidates.value.length > 0) return ''
  return 'Não há outra trilha para comandar esta.'
})
const musicNote = computed(() => background.value === 'MUS' && rules.value.length > 0)

function add(): void {
  const id = background.value
  const key = candidates.value[0]
  if (!id || !key) return
  editor.flushPendingEdits()
  editor.mutate((draft) => addRuleIn(draft, id, key))
}

const remove = (index: number) => {
  editor.flushPendingEdits()
  editor.mutate((draft) => removeRuleIn(draft, index))
}

function changeKey(index: number, key: string): void {
  editor.flushPendingEdits()
  editor.setField(`${DUCKS_PATH}.${index}.key`, key)
}

function changeNumber(index: number, name: DuckFieldName, value: number | null): void {
  if (value === null) return
  editor.setField(`${DUCKS_PATH}.${index}.${name}`, clampDuck(name, value))
}
</script>

<template>
  <section v-if="background" class="duck" aria-label="Auto Duck" data-auto-duck>
    <header class="duck__head">
      <div class="duck__heading">
        <h4 class="duck__title">Abaixar sob outra trilha (Auto Duck)</h4>
        <p class="duck__target">{{ nameOf(background) }}</p>
      </div>
      <AppButton size="sm" :disabled="candidates.length === 0" title="Abaixar esta trilha enquanto outra fala" data-duck-add @click="add">
        <AppIcon name="plus" :size="16" />
        Regra
      </AppButton>
    </header>

    <p v-if="reason" class="duck__note" data-duck-reason>{{ reason }}</p>
    <p v-if="musicNote" class="duck__note" data-duck-music>
      Com uma regra aqui, o ducking antigo da música (que abaixa sob a voz) deixa de rodar: a regra é o caso da música.
    </p>
    <p v-if="rules.length === 0 && !reason" class="duck__note" data-duck-empty>
      Nenhuma regra. Use o botão Regra para abaixar esta trilha enquanto outra fala.
    </p>

    <ul v-if="rules.length > 0" class="duck__list">
      <li v-for="{ rule, index } in rules" :key="index" class="duck__rule" :data-duck-rule="index">
        <div class="duck__rule-head">
          <AppSelect
            label="Abaixa sob"
            :model-value="rule.key"
            :options="candidates.map((id) => ({ value: id, label: nameOf(id) }))"
            @update:model-value="changeKey(index, $event)"
          />
          <AppButton size="sm" variant="ghost" aria-label="Tirar a regra" title="Tirar a regra" data-duck-remove @click="remove(index)">
            <AppIcon name="trash" :size="16" />
          </AppButton>
        </div>
        <div class="duck__fields">
          <AppNumberInput
            v-for="field in DUCK_FIELDS"
            :key="field.name"
            :label="field.label"
            :model-value="duckValue(rule, field.name)"
            :min="field.min"
            :max="field.max"
            :unit="field.unit"
            :data-duck-field="field.name"
            @update:model-value="changeNumber(index, field.name, $event)"
          />
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.duck {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.duck__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2) var(--space-3);
}

.duck__heading {
  flex: 1 1 8rem;
  min-width: 0;
}

.duck__title {
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.duck__target,
.duck__note {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.duck__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.duck__rule {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.duck__rule-head {
  display: flex;
  align-items: flex-end;
  gap: var(--space-2);
}

.duck__rule-head > :first-child {
  flex: 1 1 auto;
}

.duck__fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}
</style>
