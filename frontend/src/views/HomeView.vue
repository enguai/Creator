<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import ProductCard from '../components/ProductCard.vue'
import { products } from '../data/products'

const activeSlide = ref(0)
const paused = ref(false)
let carouselTimer

const selectSlide = (index) => {
  activeSlide.value = index
}

const nextSlide = () => {
  if (!paused.value) activeSlide.value = (activeSlide.value + 1) % products.length
}

onMounted(() => {
  carouselTimer = window.setInterval(nextSlide, 6000)
})

onBeforeUnmount(() => {
  window.clearInterval(carouselTimer)
})
</script>

<template>
  <div>
    <section
      class="product-carousel"
      aria-label="造物者产品轮播"
      @mouseenter="paused = true"
      @mouseleave="paused = false"
      @focusin="paused = true"
      @focusout="paused = false"
    >
      <article
        v-for="(product, index) in products"
        :key="product.id"
        class="carousel-slide"
        :class="[`slide-${product.tone}`, { active: activeSlide === index }]"
        :aria-hidden="activeSlide !== index"
      >
        <div class="carousel-copy">
          <p class="eyebrow">{{ product.number }} · {{ product.en }}</p>
          <h1>{{ product.name }}</h1>
          <p class="carousel-tagline">{{ product.tagline }}</p>
          <p class="carousel-description">{{ product.description }}</p>
          <RouterLink class="text-link" :to="product.route" :tabindex="activeSlide === index ? 0 : -1">
            查看产品详情 <span>↗</span>
          </RouterLink>
        </div>
        <div class="carousel-image">
          <img :src="product.image" :alt="`${product.name}产品主视觉`" />
        </div>
      </article>

      <div class="carousel-dots" role="tablist" aria-label="选择轮播产品">
        <button
          v-for="(product, index) in products"
          :key="product.id"
          type="button"
          role="tab"
          :class="{ active: activeSlide === index }"
          :aria-selected="activeSlide === index"
          :aria-label="`查看${product.name}`"
          @click="selectSlide(index)"
        ><span></span></button>
      </div>
    </section>

    <section class="section collection-section home-products">
      <div class="container section-heading">
        <div>
          <p class="eyebrow">THE COLLECTION</p>
          <h2>三款核心护理，回应不同肌肤状态</h2>
        </div>
        <RouterLink class="quiet-link" to="/products">浏览全部产品 →</RouterLink>
      </div>
      <div class="container product-stack">
        <ProductCard v-for="product in products" :key="product.id" :product="product" />
      </div>
    </section>

    <section class="statement section container">
      <p class="eyebrow">OUR POINT OF VIEW</p>
      <div class="statement-grid">
        <h2>护肤不该制造焦虑，<br />它是回到自己的片刻。</h2>
        <div>
          <p>在镜头与现实之间，我们更关心肌肤真正的感受。造物者以温和、清晰、可坚持的产品体验，陪伴每一次认真生活的出场。</p>
          <p class="serif-quote">“Real skin. Real moments.”</p>
        </div>
      </div>
    </section>

    <section class="ritual-band">
      <div class="container ritual-grid">
        <div><p class="eyebrow light">BEFORE THE LIGHTS</p><h2>开播前，留 15 分钟给自己</h2></div>
        <div class="ritual-steps">
          <p><span>01</span>清洁双手与面部，让肌肤回归干净状态。</p>
          <p><span>02</span>根据当下需求，选择水润、抛光或眼周护理。</p>
          <p><span>03</span>安静等待，整理呼吸，也整理今天的自己。</p>
        </div>
      </div>
    </section>
  </div>
</template>
