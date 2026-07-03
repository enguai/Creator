import camelliaImage from '../assets/images/camellia-mask.png'
import polishingImage from '../assets/images/polishing-mask.png'
import eyeMaskImage from '../assets/images/agate-eye-mask.png'

export const products = [
  {
    id: 'camellia',
    number: '01',
    name: '红山茶软膜',
    en: 'Red Camellia Soft Mask',
    tagline: '丰润补水，细致包裹每一寸肌肤',
    description: '以红山茶意象为灵感的居家软膜护理，为忙碌生活留出一段安静、丰润的肌肤时间。',
    benefits: ['水润包裹', '柔软肤感', '居家仪式'],
    image: camelliaImage,
    tone: 'rose',
  },
  {
    id: 'polishing',
    number: '02',
    name: '抛光面膜',
    en: 'Polishing Facial Mask',
    tagline: '抚平倦意，重现细腻通透的光泽感',
    description: '关注粗糙、暗沉与疲惫观感，以温和的护理节奏，帮助肌肤呈现细腻、平整的视觉质感。',
    benefits: ['细腻触感', '通透观感', '柔润焕亮'],
    image: polishingImage,
    tone: 'sand',
  },
  {
    id: 'agate-eye',
    number: '03',
    name: '冰玛瑙眼膜',
    en: 'Ice Agate Eye Mask',
    tagline: '冰感沁润，让眼周回到舒展状态',
    description: '贴合眼下弧度的凝胶质地，在需要迅速整理状态的清晨与直播前，带来清凉水润的使用体验。',
    benefits: ['冰感沁润', '眼周贴合', '状态焕新'],
    image: eyeMaskImage,
    tone: 'pearl',
  },
]
