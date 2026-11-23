// Same rule as backend/app/services/brand.py, so the preview matches the saved card.
const INK = "#1B1916";
const IVORY = "#FBF9F4";

function channel(c: number) {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string) {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrast(a: string, b: string) {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

export function cardText(background: string) {
  if (!/^#[0-9a-fA-F]{6}$/.test(background)) return INK;
  const best = contrast(background, INK) >= contrast(background, IVORY) ? INK : IVORY;
  if (contrast(background, best) >= 4.5) return best;
  return contrast(background, "#000000") >= contrast(background, "#FFFFFF") ? "#000000" : "#FFFFFF";
}
