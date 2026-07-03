<script setup>
import { products } from '../data/products'
</script>

<template>
  <div>
    <section class="page-intro container">
      <p class="eyebrow">OUR PRODUCTS</p>
      <h1>为真实状态而生的<br />三款核心护理</h1>
      <p>不追逐繁复步骤，回到肤感、质地与使用场景本身。</p>
    </section>

    <section class="product-editorial">
      <article v-for="(product, index) in products" :id="product.id" :key="product.id" class="editorial-row" :class="{ reverse: index % 2 }">
        <div class="editorial-image"><img :src="product.image" :alt="`${product.name}产品图`" /></div>
        <div class="editorial-copy">
          <span class="large-number">{{ product.number }}</span>
          <p class="eyebrow">{{ product.en }}</p>
          <h2>{{ product.name }}</h2>
          <h3>{{ product.tagline }}</h3>
          <p>{{ product.description }}</p>
          <div class="benefit-row"><span v-for="benefit in product.benefits" :key="benefit">{{ benefit }}</span></div>
          <RouterLink class="text-link" to="/features">查看使用场景 <span>↗</span></RouterLink>
        </div>
      </article>
    </section>

    <section class="selection-guide section container">
      <div class="section-heading"><div><p class="eyebrow">YOUR RITUAL</p><h2>今天，肌肤需要什么？</h2></div></div>
      <div class="guide-grid">
        <div><span>水润不足</span><h3>选择红山茶软膜</h3><p>适合希望获得丰润包裹感、让肌肤看起来柔软有光泽的时刻。</p></div>
        <div><span>粗糙暗沉</span><h3>选择抛光面膜</h3><p>适合妆前或重要出镜前，为肌肤整理细腻、通透的视觉状态。</p></div>
        <div><span>眼周疲惫</span><h3>选择冰玛瑙眼膜</h3><p>适合清晨与长时间工作后，用清凉贴合感唤回眼周舒展状态。</p></div>
      </div>
    </section>
  </div>
</template>
