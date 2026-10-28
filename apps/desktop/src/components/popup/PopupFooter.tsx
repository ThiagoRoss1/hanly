import type { PopupContent } from "../../contracts/desktop.ts";

export function PopupFooter({
  content,
  detailLevel,
  expanded,
  canExpand,
  senseCount,
  onToggleExpanded,
}: {
  content: PopupContent;
  detailLevel: string;
  expanded: boolean;
  canExpand: boolean;
  senseCount: number;
  onToggleExpanded: () => void;
}) {
  const technical = content.technical_lines ?? [];

  return (
    <footer className="flex min-h-[50px] flex-none items-center gap-2 px-[18px] pt-[10px] pb-3 max-[361px]:px-4">
      {detailLevel === "basic" && technical.length > 0 && (
        <span className="max-w-[58%] m-0 text-[12px] leading-5 [color:var(--popup-muted)] [font-family:var(--popup-display-font)] [overflow-wrap:anywhere]">
          {technical.join(" · ")}
        </span>
      )}
      <span className="text-[11px] leading-[18px] [color:var(--popup-muted)] [font-family:var(--popup-display-font)]">
        {!expanded && senseCount > 2
          ? "+" + String(senseCount - 2) + " more meanings"
          : ""}
      </span>
      <span className="flex-1" />
      {canExpand && (
        <button
          aria-expanded={expanded}
          className="popup-button relative isolate flex min-h-[32px] items-center justify-center gap-2 border-0 rounded-none bg-transparent px-3 pt-[5px] pb-[7px] text-[11px] leading-4 [color:var(--popup-ink)] !font-[family-name:var(--popup-bold-font)] cursor-pointer"
          onClick={onToggleExpanded}
          type="button"
        >
          <span>{expanded ? "Less detail" : "Details"}</span>
          <img
            alt=""
            className="h-[18px] w-[18px] flex-none object-contain [image-rendering:pixelated]"
            src={
              expanded
                ? "/design/media/assets/icons/custom/icon-details-minus.svg"
                : "/design/media/assets/icons/custom/icon-details-plus.svg"
            }
          />
        </button>
      )}
    </footer>
  );
}
