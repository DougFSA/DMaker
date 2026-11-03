<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, type InfographicInfo } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'

const props = defineProps<{ info: InfographicInfo; brand?: string; selected?: boolean }>()
defineEmits<{ choose: [info: InfographicInfo] }>()

type PreviewState = 'loading' | 'ready' | 'failed'
const state = ref<PreviewState>('loading')
// o servidor gera o quadro na primeira vez que alguém pede; `attempt` força o navegador a pedir de novo
const attempt = ref(0)

const previewUrl = computed(() => {
  const url = api.infographics.previewUrl(props.info.name, props.brand)
  if (!attempt.value) return url
  return `${url}${url.includes('?') ? '&' : '?'}tentativa=${attempt.value}`
})
const description = computed(() => `Quadro de exemplo do infográfico ${props.info.title}`)

watch(
  () => props.brand,
  () => {
    state.value = 'loading'
  },
)

function retry(): void {
  attempt.value += 1
  state.value = 'loading'
}
</script>

<template>
  <article class="infographic" :class="{ 'infographic--selected': selected }">
    <header class="infographic__head">
      <h3 class="infographic__title">{{ info.title }}</h3>
      <code class="infographic__name">{{ info.name }}</code>
    </header>
    <p class="infographic__description">{{ info.description }}</p>

    <div class="infographic__preview" :data-state="state">
      <img
        v-show="state !== 'failed'"
        :key="previewUrl"
        :src="previewUrl"
        :alt="description"
        loading="lazy"
        @load="state = 'ready'"
        @error="state = 'failed'"
      />
      <p v-if="state === 'loading'" class="infographic__status" role="status">Gerando o quadro...</p>
      <div v-if="state === 'failed'" class="infographic__failed" role="alert">
        <AppIcon name="alert" :size="18" />
        <span>Não foi possível gerar o quadro.</span>
        <AppButton size="sm" @click="retry">Tentar de novo</AppButton>
      </div>
    </div>

    <footer class="infographic__foot">
      <AppButton size="sm" :variant="selected ? 'primary' : 'secondary'" @click="$emit('choose', info)">
        {{ selected ? 'Escolhido' : 'Ajustar os valores' }}
      </AppButton>
    </footer>
  </article>
</template>

<style scoped>
.infographic {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  transition:
    border-color var(--transition),
    box-shadow var(--transition);
}

.infographic:hover,
.infographic--selected {
  border-color: var(--color-accent-soft);
  box-shadow: var(--glow-accent);
}

.infographic__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-3);
}

.infographic__title {
  font-size: var(--text-base);
  font-weight: 600;
}

.infographic__name {
  font-family: ui-monospace, monospace;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.infographic__description {
  min-height: 3.9em;
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.infographic__preview {
  position: relative;
  min-height: 6rem;
  overflow: hidden;
  border-radius: var(--radius-md);
  background: #0f172a;
}

.infographic__preview img {
  display: block;
  width: 100%;
  height: auto;
}

.infographic__status {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  pointer-events: none;
}

.infographic__preview[data-state='ready'] .infographic__status {
  display: none;
}

.infographic__failed {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-error);
}

.infographic__foot {
  display: flex;
  justify-content: flex-end;
}
</style>
