<script setup lang="ts">
/* Desenhar uma voz por descrição, sem gravação: gênero, faixa etária, tom e sotaque, ou um texto livre que vale
   no lugar deles. Depois de criar, a voz nova já fica escolhida para o roteiro. */
import { computed, reactive, ref } from 'vue'
import { errorMessage, type VoiceDesignOptions, type VoiceOption } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import AppInput from '@/components/ui/AppInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import { designRequest, type DesignFormState } from '@/lib/voice'
import { useToastsStore } from '@/stores/toasts'
import { useVoiceStore } from '@/stores/voice'

defineProps<{ options: VoiceDesignOptions; brands: VoiceOption[] }>()

const NOT_SET = 'Não definir'

const voices = useVoiceStore()
const toasts = useToastsStore()

function emptyForm(): DesignFormState {
  return {
    name: '',
    gender: '',
    age: '',
    pitch: '',
    accent: '',
    language: 'pt',
    brand: '',
    whisper: false,
    instruct: '',
  }
}

const form = reactive<DesignFormState>(emptyForm())
const busy = ref(false)
const nameError = ref('')
const hasInstruct = computed(() => form.instruct.trim() !== '')

async function submit(): Promise<void> {
  if (!form.name.trim()) {
    nameError.value = 'Dê um nome para a voz.'
    return
  }
  nameError.value = ''
  busy.value = true
  try {
    const profile = await voices.design(designRequest(form))
    toasts.push({ tone: 'success', title: `Voz "${profile.name}" criada`, description: 'Já está escolhida para o roteiro.' })
    // o nome volta em branco; as características ficam, porque a próxima voz costuma ser parecida
    form.name = ''
  } catch (error) {
    toasts.push({ tone: 'error', title: 'Não consegui criar a voz', description: errorMessage(error) })
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <form class="design" novalidate @submit.prevent="submit">
    <p class="intro">Descreva como a voz soa. Não precisa de gravação.</p>

    <AppInput
      v-model="form.name"
      label="Nome da voz"
      placeholder="Ex.: Narradora grave"
      :error="nameError"
      required
    />

    <div class="design__grid">
      <AppSelect v-model="form.gender" label="Gênero" :options="options.gender" :placeholder="NOT_SET" />
      <AppSelect v-model="form.age" label="Faixa etária" :options="options.age" :placeholder="NOT_SET" />
      <AppSelect v-model="form.pitch" label="Tom" :options="options.pitch" :placeholder="NOT_SET" />
      <AppSelect v-model="form.accent" label="Sotaque" :options="options.accent" :placeholder="NOT_SET" />
      <AppSelect v-model="form.language" label="Idioma" :options="options.languages" />
    </div>

    <AppSelect
      v-model="form.brand"
      label="Marca"
      :options="brands"
      placeholder="Sem marca (serve para qualquer uma)"
    />

    <AppCheckbox v-model="form.whisper" label="Voz sussurrada" />

    <AppInput
      v-model="form.instruct"
      label="Descrição livre (opcional)"
      placeholder="Ex.: female, low pitch, british accent"
      :hint="hasInstruct ? 'Com a descrição livre, ela vale no lugar de gênero, idade, tom e sotaque.' : undefined"
    />

    <div>
      <AppButton type="submit" variant="primary" :loading="busy">{{ busy ? 'Criando...' : 'Criar voz' }}</AppButton>
    </div>
  </form>
</template>

<style scoped>
.design {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.intro {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.design__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
  gap: var(--space-4);
}
</style>
