import camelliaImage from '../assets/products/camellia/02.jpg'
import polishingImage from '../assets/products/polishing/02.jpg'
import eyeMaskImage from '../assets/products/agate/01.jpg'

const collectImages = (modules) => Object.entries(modules)
  .sort(([a], [b]) => a.localeCompare(b, 'zh-CN', { numeric: true }))
  .map(([, image]) => image)

const camelliaDetails = collectImages(import.meta.glob(
  '../assets/products/camellia/*',
  { eager: true, import: 'default' },
))

const polishingDetails = collectImages(import.meta.glob(
  '../assets/products/polishing/*',
  { eager: true, import: 'default' },
))

const eyeMaskDetails = collectImages(import.meta.glob(
  '../assets/products/agate/*',
  { eager: true, import: 'default' },
))

export const products = [
  {
    id: 'camellia',
    number: '01',
    name: '山茶花软膜',
    en: 'Red Camellia Soft Mask',
    tagline: '15 分钟紧致，7 天淡化三大纹',
    description: '以红山茶精粹、仿生蛋白绷带技术与水油双相护理，为肌肤带来柔润包裹感，适合居家密集护理。',
    benefits: ['紧致淡纹', '水润滋养', '柔软肤感'],
    image: camelliaImage,
    detailImages: camelliaDetails,
    route: '/products/camellia',
    tone: 'rose',
  },
  {
    id: 'polishing',
    number: '02',
    name: '小气泡抛光面膜',
    en: 'Micro-Bubble Polishing Mask',
    tagline: '15 分钟收毛孔，敷出细腻抛光肌',
    description: '双管分装的精华乳与碳酸精华露现用现配，从清洁、提亮到柔润养护，一次完成温和的居家抛光护理。',
    benefits: ['净澈毛孔', '细腻抛光', '温和焕亮'],
    image: polishingImage,
    detailImages: polishingDetails,
    route: '/products/polishing',
    tone: 'sand',
  },
  {
    id: 'agate-eye',
    number: '03',
    name: '冰玛瑙眼膜',
    en: 'Ice Agate Eye Mask',
    tagline: '7 天淡眼纹，紧致塑眼周',
    description: '胶原肽紧塑淡纹眼膜贴合眼周轮廓，以凝润触感集中护理干纹与疲惫观感，帮助眼周恢复舒展状态。',
    benefits: ['淡化眼纹', '紧致眼周', '凝润贴合'],
    image: eyeMaskImage,
    detailImages: eyeMaskDetails,
    route: '/products/agate-eye',
    tone: 'pearl',
  },
]
