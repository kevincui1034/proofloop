"use client";

/**
 * The Proofloop gate — two posts and an amber-trimmed lintel.
 * Purely decorative; scales to its parent width (160:220 aspect).
 */
export default function GateStructure({ className = "" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 160 220"
      aria-hidden="true"
      focusable="false"
      className={`block ${className}`}
    >
      {/* posts */}
      <rect x="18" y="52" width="16" height="164" rx="6" fill="#131a25" stroke="#2b3544" strokeWidth="2" />
      <rect x="126" y="52" width="16" height="164" rx="6" fill="#131a25" stroke="#2b3544" strokeWidth="2" />
      {/* post trim */}
      <line x1="26" y1="60" x2="26" y2="208" stroke="var(--amber)" strokeWidth="2" opacity="0.35" />
      <line x1="134" y1="60" x2="134" y2="208" stroke="var(--amber)" strokeWidth="2" opacity="0.35" />
      {/* lintel */}
      <rect x="6" y="34" width="148" height="18" rx="7" fill="#131a25" stroke="#2b3544" strokeWidth="2" />
      <line x1="12" y1="38" x2="148" y2="38" stroke="var(--amber)" strokeWidth="2.5" opacity="0.9" />
      {/* scales badge on the lintel */}
      <g transform="translate(80 43)" stroke="var(--amber)" strokeWidth="1.4" strokeLinecap="round" fill="none">
        <line x1="0" y1="-4" x2="0" y2="4" />
        <line x1="-5" y1="-2.5" x2="5" y2="-2.5" />
        <path d="M-7.5 -1 a2.5 2.5 0 0 0 5 0" />
        <path d="M2.5 -1 a2.5 2.5 0 0 0 5 0" />
      </g>
      {/* beacon */}
      <circle cx="80" cy="28" r="3" fill="var(--amber)" opacity="0.9" />
    </svg>
  );
}
