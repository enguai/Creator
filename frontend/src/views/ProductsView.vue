<script setup>
import { products } from '../data/products'
</script>

<template>
  <div>
    <section class="page-intro container">
      <p class="eyebrow">OUR PRODUCTS</p>
      <h1>三款核心护理，<br />各有清晰的答案</h1>
      <p>依次探索山茶花软膜、小气泡抛光面膜与冰玛瑙眼膜的完整产品详情。</p>
    </section>

    <section class="product-index container" aria-label="产品子页面">
      <RouterLink
        v-for="product in products"
        :key="product.id"
        :to="product.route"
        class="product-entry"
        :class="`entry-${product.tone}`"
      >
        <div class="product-entry-image">
          <img :src="product.image" :alt="`${product.name}产品主视觉`" />
        </div>
        <div class="product-entry-copy">
          <span class="large-number">{{ product.number }}</span>
          <p class="eyebrow">{{ product.en }}</p>
          <h2>{{ product.name }}</h2>
          <h3>{{ product.tagline }}</h3>
          <p>{{ product.description }}</p>
          <ul class="tag-list" aria-label="产品特点">
            <li v-for="benefit in product.benefits" :key="benefit">{{ benefit }}</li>
          </ul>
          <span class="entry-link">进入产品页面 <b>↗</b></span>
        </div>
      </RouterLink>
    </section>

    <section class="product-index-note">
      <div class="container">
        <p class="eyebrow light">CHOOSE YOUR RITUAL</p>
        <h2>从肌肤此刻的需要出发</h2>
        <p>丰润紧致、细腻抛光或眼周淡纹，让每一次护理都有明确方向。</p>
      </div>
    </section>
  </div>
</template>
