type StampProps = {
  verdict: "blocked" | "allowed";
  /** Override the stamped text (e.g. "DEPLOY BLOCKED"). */
  text?: string;
  size?: "sm" | "md" | "lg" | "xl";
  className?: string;
};

const SIZES: Record<NonNullable<StampProps["size"]>, string> = {
  sm: "border-2 px-2.5 py-0.5 text-xs",
  md: "border-[3px] px-4 py-1 text-lg sm:text-xl",
  lg: "border-4 px-6 py-1.5 text-2xl sm:text-4xl",
  // fluid below sm — "DEPLOY BLOCKED" must fit a 375px screen at scale 1
  xl: "border-[3px] sm:border-[5px] px-[3vw] sm:px-7 py-2 text-[7vw] sm:text-6xl md:text-7xl",
};

/**
 * A rubber-stamp verdict. Pure DOM (cheap to scale in the S4 slam), inked
 * via the .stamp-ink erosion mask, colored by the current world's verdict
 * tokens. Rotation/placement belongs to the caller.
 */
export default function Stamp({
  verdict,
  text,
  size = "md",
  className = "",
}: StampProps) {
  const red = verdict === "blocked";
  return (
    <span
      className={`stamp-ink inline-block select-none whitespace-nowrap rounded-md font-sans font-extrabold uppercase leading-none tracking-[0.14em] ${
        red
          ? "border-verdict-red-deep text-verdict-red-deep"
          : "border-verdict-green text-verdict-green"
      } ${SIZES[size]} ${className}`}
    >
      {text ?? (red ? "Blocked" : "Allowed")}
    </span>
  );
}
