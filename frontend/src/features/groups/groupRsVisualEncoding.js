import { BREADTH_VISUAL_COLORS } from '../../components/Breadth/breadthVisualEncoding';

export const groupRsTone = (value) => {
  if (!Number.isFinite(value)) return 'neutral';
  if (value >= 80) return 'up-strong';
  if (value >= 70) return 'up-soft';
  if (value <= 20) return 'down-strong';
  if (value <= 30) return 'down-soft';
  return 'neutral';
};

export const groupRsCellSx = (value) => {
  const tone = groupRsTone(value);
  if (tone === 'neutral') return {};

  return {
    backgroundColor: BREADTH_VISUAL_COLORS[tone],
    color: '#fff',
    fontWeight: 600,
  };
};
