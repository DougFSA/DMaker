<script setup lang="ts">
/* A tela do editor sem projeto (o item "Editor" do menu): a lista de projetos, com o último aberto em destaque. */
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api, errorMessage, type ProjectListItem } from '@/api'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { useWorkspaceStore } from '@/stores/workspace'

const workspace = useWorkspaceStore()

const projects = ref<ProjectListItem[]>([])
const loading = ref(true)
const failure = ref('')

onMounted(async () => {
  try {
    projects.value = await api.projects.list()
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <AppCard>
    <p v-if="loading" class="status" role="status">Carregando os projetos...</p>
    <p v-else-if="failure" class="status status--error" role="alert">{{ failure }}</p>
    <EmptyState
      v-else-if="projects.length === 0"
      icon="film"
      title="Nenhum projeto ainda"
      description="Crie um projeto em Projetos para editar aqui."
    >
      <AppButton to="/projetos" variant="primary">Ir para Projetos</AppButton>
    </EmptyState>
    <template v-else>
      <div v-if="workspace.currentProject" class="resume">
        <span>Último projeto aberto: <strong>{{ workspace.currentProject }}</strong></span>
        <AppButton :to="{ name: 'editor', params: { name: workspace.currentProject } }" variant="primary">
          Continuar editando
        </AppButton>
      </div>
      <ul class="list" aria-label="Projetos">
        <li v-for="project in projects" :key="project.name">
          <RouterLink :to="{ name: 'editor', params: { name: project.name } }" class="item">
            <strong>{{ project.name }}</strong>
            <span v-if="project.error" class="item__error">spec com erro: abre no editor para consertar</span>
            <span v-else class="item__meta">
              {{ project.preset ?? 'sem formato' }} · {{ project.brand || 'sem marca' }}
              <AppBadge>{{ project.segments ?? 0 }} {{ project.segments === 1 ? 'trecho' : 'trechos' }}</AppBadge>
            </span>
          </RouterLink>
        </li>
      </ul>
    </template>
  </AppCard>
</template>

<style scoped>
.status {
  color: var(--color-text-soft);
}

.status--error {
  color: var(--color-error);
}

.resume {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  background: var(--color-accent-bg);
}

.list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
  gap: var(--space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text);
  text-decoration: none;
  transition:
    border-color var(--transition),
    background var(--transition);
}

.item:hover {
  border-color: var(--color-accent-soft);
  background: var(--color-surface-hover);
  text-decoration: none;
}

.item__meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.item__error {
  font-size: var(--text-sm);
  color: var(--color-warning);
}
</style>
