<script setup>
import ProductCard from '../components/ProductCard.vue'
import { products } from '../data/products'
</script>

<template>
  <div>
    <section class="home-hero">
      <div class="hero-visual" :style="{ backgroundImage: `url(${products[0].image})` }"></div>
      <div class="container hero-copy">
        <p class="eyebrow">CREATOR · SKIN RITUALS</p>
        <h1>把日常护理<br />做成一件值得期待的事</h1>
        <p class="hero-lead">专注直播时代的真实肌肤需求，用恰到好处的产品与内容，让每一次出镜都更从容。</p>
        <RouterLink class="text-link" to="/products">探索产品 <span>↗</span></RouterLink>
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

    <section class="section collection-section">
      <div class="container section-heading">
        <div><p class="eyebrow">THE COLLECTION</p><h2>三种护理，回应三种状态</h2></div>
        <RouterLink class="quiet-link" to="/features">了解护理逻辑 →</RouterLink>
      </div>
      <div class="container product-stack">
        <ProductCard v-for="product in products" :key="product.id" :product="product" />
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
