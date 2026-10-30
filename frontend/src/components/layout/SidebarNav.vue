<script setup lang="ts">
import { RouterLink } from 'vue-router'
import AppIcon from '@/components/ui/AppIcon.vue'
import { CLASSIC_UI_PATH, NAV_ITEMS } from '@/navigation'

defineProps<{ collapsed: boolean }>()
</script>

<template>
  <nav class="nav" aria-label="Principal">
    <RouterLink to="/projetos" class="nav__brand" aria-label="DMaker, ir para Projetos">
      <span class="nav__logo" aria-hidden="true">
        <svg viewBox="0 0 32 32" width="28" height="28">
          <path
            d="M9 8h7a8 8 0 0 1 0 16H9z"
            fill="none"
            stroke="currentColor"
            stroke-width="3"
            stroke-linejoin="round"
          />
        </svg>
      </span>
      <span v-if="!collapsed" class="nav__wordmark">DMaker</span>
    </RouterLink>

    <ul class="nav__list">
      <li v-for="item in NAV_ITEMS" :key="item.key">
        <RouterLink
          :to="item.to"
          class="nav__link"
          active-class="is-active"
          :title="collapsed ? item.label : undefined"
        >
          <AppIcon :name="item.icon" />
          <span v-if="!collapsed" class="nav__label">{{ item.label }}</span>
          <span v-else class="visually-hidden">{{ item.label }}</span>
        </RouterLink>
      </li>
    </ul>

    <a :href="CLASSIC_UI_PATH" class="nav__classic" :title="collapsed ? 'Interface clássica' : undefined">
      <AppIcon name="external" :size="18" />
      <span v-if="!collapsed">Interface clássica</span>
      <span v-else class="visually-hidden">Interface clássica</span>
    </a>
  </nav>
</template>

<style scoped>
.nav {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  height: 100%;
  padding: var(--space-4) var(--space-3);
}

.nav__brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  color: var(--color-text);
  text-decoration: none;
}

.nav__brand:hover {
  text-decoration: none;
}

.nav__logo {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 2.25rem;
  height: 2.25rem;
  border-radius: var(--radius-sm);
  background: var(--color-accent-bg);
  color: var(--color-accent-text);
}

.nav__wordmark {
  font-size: var(--text-lg);
  font-weight: 700;
  letter-spacing: -0.02em;
}

.nav__list {
  display: flex;
  flex-direction: column;
  flex: 1;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.nav__link,
.nav__classic {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: 2.75rem;
  padding: 0.5rem var(--space-3);
  border-radius: var(--radius-md);
  color: var(--color-text-soft);
  font-size: var(--text-md);
  font-weight: 500;
  text-decoration: none;
  transition:
    background var(--transition),
    color var(--transition);
}

.nav__link:hover,
.nav__classic:hover {
  background: var(--color-surface-hover);
  color: var(--color-text);
  text-decoration: none;
}

.nav__link.is-active {
  background: var(--color-accent-bg);
  color: var(--color-accent-text);
  box-shadow: inset 3px 0 0 var(--color-accent);
}

.nav__label {
  flex: 1;
}

.nav__classic {
  border: 1px dashed var(--color-border-strong);
  font-size: var(--text-sm);
}
</style>
