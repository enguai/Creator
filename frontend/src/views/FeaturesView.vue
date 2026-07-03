<script setup>
import { products } from '../data/products'
</script>

<template>
  <div>
    <section class="feature-hero split-hero">
      <div class="split-copy">
        <p class="eyebrow">FORM & FUNCTION</p>
        <h1>质地、贴合与节奏，<br />共同决定一次好护理</h1>
        <p>我们把复杂的护肤语言，翻译成可感知、可坚持的日常体验。</p>
      </div>
      <div class="split-image"><img :src="products[2].image" alt="冰玛瑙眼膜质地特写" /></div>
    </section>

    <section class="section container feature-principles">
      <p class="eyebrow">THREE PRINCIPLES</p>
      <div class="principle-grid">
        <article><span>01</span><h2>包裹</h2><p>软膜与凝胶贴合肌肤轮廓，让护理停留在需要它的位置，也让片刻休息变得具体。</p></article>
        <article><span>02</span><h2>触感</h2><p>从柔润到冰凉，不同质地回应不同状态；看得见的光泽，往往先来自舒适肤感。</p></article>
        <article><span>03</span><h2>节奏</h2><p>不堆叠过多步骤，把每一次护理放进真实生活：清晨、妆前、直播前，或安静的夜晚。</p></article>
      </div>
    </section>

    <section class="texture-section">
      <div class="container texture-grid">
        <div class="texture-photo"><img :src="products[1].image" alt="抛光面膜细腻质地" /></div>
        <div class="texture-copy">
          <p class="eyebrow">TEXTURE MATTERS</p>
          <h2>细节决定<br />肌肤愿不愿意坚持</h2>
          <dl>
            <div><dt>贴合轮廓</dt><dd>适配面部与眼周的使用区域，减少护理过程中的打扰。</dd></div>
            <div><dt>易于融入</dt><dd>清楚的使用场景，让产品自然进入已有的生活节奏。</dd></div>
            <div><dt>真实可感</dt><dd>关注即时肤感与使用体验，不过度承诺，不制造焦虑。</dd></div>
          </dl>
        </div>
      </div>
    </section>

    <section class="section container routine-table">
      <p class="eyebrow">WEEKLY ROUTINE</p><h2>一周护理参考</h2>
      <div class="routine-row"><span>MON</span><strong>冰玛瑙眼膜</strong><p>清晨状态整理</p></div>
      <div class="routine-row"><span>WED</span><strong>抛光面膜</strong><p>周中细腻焕新</p></div>
      <div class="routine-row"><span>SUN</span><strong>红山茶软膜</strong><p>周末丰润休息</p></div>
      <small>请以产品实际说明与个人肌肤状态为准。</small>
    </section>
  </div>
</template>
