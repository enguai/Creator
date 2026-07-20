<script setup>
import brandHomeImage from '../assets/images/brand-home.jpg'
import camelliaMainImage from '../assets/images/camellia-main.jpg'
import polishingMainImage from '../assets/images/polishing-main.jpg'
import agateMainImage from '../assets/images/agate-main.jpg'
</script>

<template>
  <div>
    <section class="brand-hero" :style="{ '--brand-hero-image': `url(${brandHomeImage})` }">
      <div class="container brand-hero-inner">
        <div>
          <p class="eyebrow">ABOUT CREATOR</p>
          <h1>护肤的终极意义，<br />从不是刻意雕琢完美，<br />而是找回松弛、从容、<br />不被定义的 <span>自在好状态</span></h1>
        </div>
      </div>
    </section>
    <section class="section container brand-story">
      <div><p class="eyebrow">OUR STORY</p><h2>从直播间出发，<br />也回到真实生活。</h2></div>
      <div class="story-copy"><p>镜头让我们更快地看见需求，也更直接地听见反馈。造物者直播部门从一个个真实的使用场景出发，把用户关心的肤感、步骤与状态，放回产品表达的中心。</p><p>我们相信，高级感不是距离，而是克制、诚实与恰到好处。好的产品不喧哗，它在需要的时候出现，让人感到被理解。</p></div>
    </section>
    <section class="brand-image-band" aria-label="造物者三款产品主图">
      <img :src="camelliaMainImage" alt="造物者红山茶软膜" />
      <img :src="polishingMainImage" alt="造物者小气泡抛光面膜" />
      <img :src="agateMainImage" alt="造物者冰玛瑙眼膜" />
    </section>
    <section class="section container values-section">
      <div class="section-heading"><div><p class="eyebrow">OUR VALUES</p><h2>我们在意的事</h2></div></div>
      <div class="value-grid">
        <article><span>01</span><h3>自在好状态</h3><p>护肤不为刻意雕琢完美，而是让肌肤与心境都回到松弛、从容、舒展自洽的状态。</p></article>
        <article><span>02</span><h3>科研造物</h3><p>以全球前沿智慧与自主研发为基础，拒绝概念护肤和无效添加，专注高效、温和的真实肤感。</p></article>
        <article><span>03</span><h3>女性悦己</h3><p>不必追赶他人的节奏，也不必迎合外界期待；在日常护理里，看见自己、接纳自己、宠爱自己。</p></article>
        <article><span>04</span><h3>温柔陪伴</h3><p>从稳定肌理到松弛心境，以科学造物之力陪伴每一位女性，让自在好状态成为日常常态。</p></article>
      </div>
    </section>
    <section class="brand-quote"><p>CREATOR</p><blockquote>造物者　<span>自在好状态</span></blockquote></section>
  </div>
</template>
