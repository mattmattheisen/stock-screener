import { BREADTH_VISUAL_COLORS } from '../../components/Breadth/breadthVisualEncoding';

export const groupRsTone = (value) => {
  if (!Number.isFinite(value)) return 'neutral';
  const displayedValue = Number(value.toFixed(1));
  if (displayedValue >= 80) return 'up-strong';
  if (displayedValue >= 70) return 'up-soft';
  if (displayedValue <= 20) return 'down-strong';
  if (displayedValue <= 30) return 'down-soft';
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
