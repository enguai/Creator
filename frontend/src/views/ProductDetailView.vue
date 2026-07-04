<script setup>
import { computed } from 'vue'
import { products } from '../data/products'

const props = defineProps({
  productId: { type: String, required: true },
})

const productIndex = computed(() => products.findIndex((item) => item.id === props.productId))
const product = computed(() => products[productIndex.value])
const nextProduct = computed(() => products[(productIndex.value + 1) % products.length])
</script>

<template>
  <div v-if="product" class="product-detail-page">
    <section class="product-detail-hero" :class="`detail-${product.tone}`">
      <div class="container product-detail-head">
        <div class="product-detail-copy">
          <RouterLink class="back-link" to="/products">← 返回全部产品</RouterLink>
          <p class="eyebrow">{{ product.number }} · {{ product.en }}</p>
          <h1>{{ product.name }}</h1>
          <h2>{{ product.tagline }}</h2>
          <p>{{ product.description }}</p>
          <ul class="tag-list" aria-label="产品特点">
            <li v-for="benefit in product.benefits" :key="benefit">{{ benefit }}</li>
          </ul>
        </div>
        <div class="product-detail-cover">
          <img :src="product.image" :alt="`${product.name}主视觉`" />
        </div>
      </div>
    </section>

    <nav class="product-subnav" aria-label="产品页面导航">
      <div class="container">
        <RouterLink
          v-for="item in products"
          :key="item.id"
          :to="item.route"
          :class="{ active: item.id === product.id }"
        >{{ item.name }}</RouterLink>
      </div>
    </nav>

    <section class="detail-gallery-section">
      <div class="detail-gallery-heading">
        <p class="eyebrow">PRODUCT DETAILS</p>
        <h2>{{ product.name }} · 完整详情</h2>
      </div>
      <div class="detail-gallery">
        <img
          v-for="(image, index) in product.detailImages"
          :key="image"
          :src="image"
          :alt="`${product.name}详情图 ${index + 1}`"
          loading="lazy"
        />
      </div>
    </section>

    <section class="next-product">
      <div class="container">
        <p class="eyebrow light">NEXT PRODUCT</p>
        <RouterLink :to="nextProduct.route">
          <span>继续探索</span>
          <strong>{{ nextProduct.name }}</strong>
          <b>→</b>
        </RouterLink>
      </div>
    </section>
  </div>
</template>
