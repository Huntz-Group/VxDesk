// Signature pastel blob backdrop: 2–3 overlapping palette circles under a
// heavy Gaussian blur. Static, purely decorative.

interface Props {
  /** which corner flavor: hero (large) or empty (small, centered) */
  variant?: 'hero' | 'empty';
}

export function Blobs({ variant = 'hero' }: Props) {
  if (variant === 'empty') {
    return (
      <svg className="blobs" viewBox="0 0 400 220" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        <filter id="blob-blur-empty" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="60" />
        </filter>
        <g filter="url(#blob-blur-empty)" opacity="0.85">
          <circle cx="150" cy="110" r="70" fill="#FFD3E0" />
          <circle cx="240" cy="90" r="60" fill="#BBE9F2" />
          <circle cx="205" cy="145" r="55" fill="#C9E7B5" />
        </g>
      </svg>
    );
  }
  return (
    <svg className="blobs" viewBox="0 0 900 260" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <filter id="blob-blur-hero" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation="80" />
      </filter>
      <g filter="url(#blob-blur-hero)" opacity="0.8">
        <circle cx="700" cy="60" r="110" fill="#FFB583" />
        <circle cx="820" cy="150" r="95" fill="#FFD3E0" />
        <circle cx="600" cy="170" r="85" fill="#BBE9F2" />
      </g>
    </svg>
  );
}
