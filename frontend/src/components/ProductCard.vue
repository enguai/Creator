<script setup>
defineProps({ product: { type: Object, required: true } })
</script>

<template>
  <article class="product-card" :class="`tone-${product.tone}`">
    <div class="product-card-image"><img :src="product.image" :alt="`${product.name}产品氛围图`" /></div>
    <div class="product-card-copy">
      <span class="product-number">{{ product.number }}</span>
      <p class="eyebrow">{{ product.en }}</p>
      <h3>{{ product.name }}</h3>
      <p>{{ product.tagline }}</p>
      <ul class="tag-list" aria-label="产品特点">
        <li v-for="benefit in product.benefits" :key="benefit">{{ benefit }}</li>
      </ul>
      <RouterLink class="product-detail-link" :to="product.route">查看产品详情 <span>→</span></RouterLink>
    </div>
  </article>
</template>
