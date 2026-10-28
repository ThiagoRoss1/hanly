import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { PixelButton } from "../PixelButton.tsx";

export function PixelSelect({
  children,
  className = "",
  ...props
}: ComponentPropsWithoutRef<"select">) {
  return (
    <span className="pixel-select">
      <select {...props} className={`select ${className}`}>
        {children}
      </select>
    </span>
  );
}

export function CaptureSetting({
  label,
  controlId,
  help,
  children,
}: {
  label: string;
  controlId: string;
  help: string;
  children: ReactNode;
}) {
  return (
    <div className="settings-row grid grid-cols-1 items-center gap-x-[14px] gap-y-2 py-3 md:grid-cols-[120px_minmax(180px,260px)_minmax(0,1fr)]">
      <label className="settings-name text-[13px] leading-[19px] font-bold" htmlFor={controlId}>
        {label}
      </label>
      <div className="settings-control flex min-w-0 items-center gap-2.5">{children}</div>
      <span className="settings-help min-w-0 [overflow-wrap:anywhere]" id={`${controlId}-help`}>
        {help}
      </span>
    </div>
  );
}

export function TargetOption({
  selected,
  disabled,
  label,
  detail,
  art,
  layout = "row",
  onSelect,
}: {
  selected: boolean;
  disabled: boolean;
  label: string;
  detail: string;
  art?: string;
  layout?: "row" | "target";
  onSelect: () => void;
}) {
  return (
    <PixelButton
      aria-checked={selected}
      className={`option group relative flex w-full items-center gap-2.5 border-0 bg-transparent px-3.5 py-[11px] text-left transition-colors aria-checked:bg-[rgb(191_167_227_/_14%)] aria-checked:shadow-none ${layout === "target" ? "min-h-[190px] flex-col justify-center gap-3.5 px-5 py-[22px] text-center whitespace-normal focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-5px]" : ""}`}
      disabled={disabled}
      onClick={onSelect}
      role="radio"
      type="button"
    >
      <span aria-hidden="true" className={`option-radio h-3.5 w-3.5 shrink-0 rounded-full border border-[var(--skin-line)] bg-[var(--surface-raised)] group-aria-checked:border-4 group-aria-checked:border-[var(--accent)] ${layout === "target" ? "absolute top-4 right-4 mt-0" : "mt-0.5"}`} />
      {art && <img className="target-art h-[60px] w-[60px] object-contain [image-rendering:pixelated]" alt="" src={art} />}
      <span className={`option-text min-w-0 ${layout === "target" ? "flex flex-col items-center gap-1.5 whitespace-normal" : "flex-1 text-left"}`}>
        <span className="option-label block text-[13px] leading-[19px] font-bold">{label}</span>
        <span className={`option-desc mt-px block text-[13px] leading-5 ${layout === "target" ? "max-w-[210px]" : "max-w-none"}`}>{detail}</span>
      </span>
    </PixelButton>
  );
}
