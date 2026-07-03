<script setup>
import logo from '../assets/images/creator-logo.jpg'
import { products } from '../data/products'
</script>

<template>
  <div>
    <section class="brand-hero">
      <div class="container brand-hero-inner">
        <div class="brand-logo-large"><img :src="logo" alt="造物者品牌标识" /></div>
        <div><p class="eyebrow">ABOUT CREATOR</p><h1>每一个认真生活的人，<br />都是自己的造物者。</h1></div>
      </div>
    </section>
    <section class="section container brand-story">
      <div><p class="eyebrow">OUR STORY</p><h2>从直播间出发，<br />也回到真实生活。</h2></div>
      <div class="story-copy"><p>镜头让我们更快地看见需求，也更直接地听见反馈。造物者直播部门从一个个真实的使用场景出发，把用户关心的肤感、步骤与状态，放回产品表达的中心。</p><p>我们相信，高级感不是距离，而是克制、诚实与恰到好处。好的产品不喧哗，它在需要的时候出现，让人感到被理解。</p></div>
    </section>
    <section class="brand-image-band"><img :src="products[0].image" alt="红山茶软膜品牌氛围" /></section>
    <section class="section container values-section">
      <div class="section-heading"><div><p class="eyebrow">OUR VALUES</p><h2>我们在意的事</h2></div></div>
      <div class="value-grid">
        <article><span>01</span><h3>真实沟通</h3><p>用清楚、克制的语言介绍产品，也认真对待每一条来自直播间的反馈。</p></article>
        <article><span>02</span><h3>长期主义</h3><p>不为短暂热度牺牲体验，让产品、内容与服务经得住反复使用。</p></article>
        <article><span>03</span><h3>女性视角</h3><p>尊重多样的生活节奏与审美选择，让护理成为力量，而非新的要求。</p></article>
        <article><span>04</span><h3>共同创造</h3><p>品牌不是单向表达；每一次互动，都在参与塑造下一个更好的答案。</p></article>
      </div>
    </section>
    <section class="brand-quote"><p>CREATOR</p><blockquote>“创造，不必惊天动地。<br />认真对待每一个普通日子，就是答案。”</blockquote></section>
  </div>
</template>
