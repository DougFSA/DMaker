<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import AppShell from '@/components/layout/AppShell.vue'
import ConfirmHost from '@/components/ui/ConfirmHost.vue'
import ToastHost from '@/components/ui/ToastHost.vue'
import { useClientHeartbeat } from '@/composables/useClientHeartbeat'
import { useJobNotifications } from '@/composables/useJobNotifications'
import { followRemoteRender } from '@/router/remoteHash'
import { useJobsStore } from '@/stores/jobs'

const jobs = useJobsStore()
const router = useRouter()

useClientHeartbeat()
useJobNotifications(router)

onMounted(async () => {
  jobs.startPolling()
  // vindo de um render da CLI/MCP, o hash aponta para o projeto e o job
  const followed = await followRemoteRender(router, window.location.hash)
  if (followed) history.replaceState(null, '', window.location.pathname)
})

onBeforeUnmount(() => jobs.stopPolling())
</script>

<template>
  <AppShell>
    <RouterView />
  </AppShell>
  <ToastHost />
  <ConfirmHost />
</template>
