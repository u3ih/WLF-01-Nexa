/** Nexa's own mark, drawn in Wealify's visual language rather than borrowed
 *  from it: thick monoline strokes with round caps in the house orange, the
 *  crossing stroke a shade deeper where it overlaps — the same construction as
 *  the Wealify "W", applied to an "N".
 *
 *  The mark stays Nexa's on purpose. This assistant tells the user, in a notice
 *  it is not allowed to hide, that its findings are "không phải kết luận chính
 *  thức của Wealify". Wearing Wealify's logo would contradict that sentence. */
export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        {/* userSpaceOnUse is required, not cosmetic: the default
            objectBoundingBox makes a gradient degenerate on a path with zero
            width, and the two uprights here are exactly that — they render as
            nothing at all under the default. */}
        <linearGradient
          id="nexa-mark-a"
          gradientUnits="userSpaceOnUse"
          x1="0" y1="32" x2="32" y2="0"
        >
          <stop offset="0%" stopColor="#ff8032" />
          <stop offset="100%" stopColor="#ff6421" />
        </linearGradient>
        <linearGradient
          id="nexa-mark-b"
          gradientUnits="userSpaceOnUse"
          x1="0" y1="0" x2="32" y2="32"
        >
          <stop offset="0%" stopColor="#fc6508" />
          <stop offset="100%" stopColor="#e5480a" />
        </linearGradient>
      </defs>
      <path
        d="M7 25V7"
        stroke="url(#nexa-mark-a)"
        strokeWidth="5.5"
        strokeLinecap="round"
      />
      <path
        d="M25 25V7"
        stroke="url(#nexa-mark-a)"
        strokeWidth="5.5"
        strokeLinecap="round"
      />
      <path
        d="M7 7L25 25"
        stroke="url(#nexa-mark-b)"
        strokeWidth="5.5"
        strokeLinecap="round"
      />
    </svg>
  );
}
