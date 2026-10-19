import type { ComponentPropsWithoutRef } from "react";

type PixelButtonProps = ComponentPropsWithoutRef<"button"> & { icon?: string };

/** A semantic button whose artwork never owns its label or hit area. */
export function PixelButton({ icon, children, className = "", type = "button", ...props }: PixelButtonProps) {
  if (!className.split(/\s+/).some((name) => ["btn", "nav-item", "segment"].includes(name))) {
    return <button {...props} type={type} className={className}>{children}</button>;
  }

  return (
    <button {...props} type={type} className={`sprite-button ${className}`}>
      <span className="button-content">
        {icon && <img className="action-icon" src={icon} alt="" />}
        <span className="button-label">{children}</span>
      </span>
    </button>
  );
}
