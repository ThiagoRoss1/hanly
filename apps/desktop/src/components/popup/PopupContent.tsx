import type { ReactNode } from "react";
import type {
  PopupContent as PopupContentData,
  PopupEntry,
  PopupSense,
} from "../../contracts/desktop.ts";
import { entryGloss, wordTypes } from "./popupModel.ts";

export function PopupSuccessContent({
  content,
  entry,
  expanded,
}: {
  content: PopupContentData;
  entry: PopupEntry;
  expanded: boolean;
}) {
  const senses = entry.senses ?? [];
  const visibleSenses = expanded ? senses : senses.slice(0, 2);
  const primarySense = visibleSenses[0];
  const analysis = content.analysis ?? [];
  const source = content.source?.toUpperCase();
  const changed = Boolean(
    content.surface && content.lemma && content.surface !== content.lemma,
  );
  const [koreanType, englishType] = wordTypes(entry.part_of_speech);

  return (
    <div className="px-[18px] pt-4 pb-2 max-[361px]:px-4">
      <header className="flex items-center gap-3 pr-7">
        <h1
          className="popup-headword min-w-0 flex-[1_1_auto] m-0 [color:var(--popup-ink)] [font-family:var(--popup-bold-font)] [overflow-wrap:anywhere]"
          lang="ko"
        >
          {entry.headword}
        </h1>
        {entry.hanja && (
          <span className="ml-auto flex-none text-[19px] leading-[26px] [color:var(--popup-muted)] [font-family:var(--popup-hanja-font)] [font-synthesis:none]">
            {entry.hanja}
          </span>
        )}
      </header>
      {koreanType && (
        <div className="mt-[5px] flex items-center gap-[6px]">
          <span className="flex-none rounded-[2px] border px-[7px] py-[2px] text-[11px] leading-4 [border-color:var(--popup-chip-line)] [background-color:var(--popup-chip-paper)] [color:var(--popup-chip-ink)] [font-family:var(--popup-display-font)]">
            {koreanType}
          </span>
          {englishType && (
            <span className="flex-none rounded-[2px] border px-[7px] py-[2px] text-[11px] leading-4 [border-color:var(--popup-chip-line)] [background-color:var(--popup-chip-paper)] [color:var(--popup-chip-ink)] [font-family:var(--popup-display-font)]">
              {englishType}
            </span>
          )}
        </div>
      )}
      {primarySense && (
        <div className="mt-[15px] mb-0 flex list-none flex-col gap-[15px] p-0">
          <PrimarySense sense={primarySense} numbered={senses.length > 1} />
          {visibleSenses.slice(1).map((sense, index) => (
            <div
              className="flex flex-col gap-[5px]"
              key={`${sense.definition ?? sense.gloss ?? "sense"}-${index}`}
            >
              <div className="flex min-w-0 items-baseline gap-2">
                <span className="min-w-4 flex-none text-[12px] leading-5 [color:var(--popup-muted)] [font-family:var(--popup-display-font)]">
                  {index + 2}.
                </span>
                <div className="popup-secondary-meaning min-w-0 [color:var(--popup-ink)] [font-family:var(--popup-bold-font)] [overflow-wrap:anywhere]">
                  {sense.gloss || sense.definition}
                </div>
              </div>
              {sense.gloss && sense.definition && (
                <p className="popup-copy m-0 ml-6 text-[14px] leading-[21px] [color:var(--popup-muted)] [font-family:var(--popup-reading-font)] [overflow-wrap:anywhere]">
                  {sense.definition}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
      {visibleSenses.length === 0 && entry.definitions?.[0] && (
        <div className="popup-meaning min-w-0 [color:var(--popup-translation)] [font-family:var(--popup-bold-font)] [overflow-wrap:anywhere]">
          {entry.definitions[0]}
        </div>
      )}
      {expanded && (analysis.length > 0 || changed || source) && (
        <PopupSection title="Read as">
          <div className="flex items-baseline justify-between gap-3">
            {changed && (
              <p className="popup-copy m-0 text-[14px] leading-[23px] [color:var(--popup-ink)] [font-family:var(--popup-reading-font)] [overflow-wrap:anywhere]">
                {content.surface} <span aria-hidden="true">→</span>{" "}
                {content.lemma}
              </p>
            )}
            {source && (
              <span className="flex-none text-[11px] leading-[18px] [color:var(--popup-muted)] [font-family:var(--popup-display-font)]">
                {source}
              </span>
            )}
          </div>
          {analysis.length > 0 && (
            <p className="popup-copy m-0 text-[14px] leading-[23px] [color:var(--popup-ink)] [font-family:var(--popup-reading-font)] [overflow-wrap:anywhere]">
              {analysis.map((piece) => piece.text).join("  +  ")}
            </p>
          )}
          {analysis.some((piece) => piece.role) && (
            <p className="m-0 text-[12px] leading-5 [color:var(--popup-muted)] [font-family:var(--popup-display-font)] [overflow-wrap:anywhere]">
              {analysis
                .map((piece) => piece.role)
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}
        </PopupSection>
      )}
      {expanded && (content.components ?? []).length > 0 && (
        <PopupSection title="How this form is built">
          {(content.components ?? []).map((component, index) => (
            <div
              className="grid grid-cols-[minmax(56px,auto)_minmax(0,1fr)] items-start gap-[10px]"
              key={`${component.surface}-${index}`}
            >
              <span
                className={`popup-copy text-[14px] leading-[23px] [font-family:var(--popup-reading-font)] [overflow-wrap:anywhere] ${component.selected ? "[color:var(--popup-translation)]" : "[color:var(--popup-ink)]"}`}
              >
                {component.surface}
              </span>
              <span
                className={`${component.grammatical ? "" : "popup-copy"} text-[14px] leading-[23px] [font-family:var(--popup-reading-font)] [overflow-wrap:anywhere] ${component.grammatical ? "text-[12px] leading-5 [color:var(--popup-muted)] [font-family:var(--popup-display-font)]" : "[color:var(--popup-ink)]"}`}
              >
                {component.gloss ??
                  (component.grammatical
                    ? "grammatical"
                    : "no dictionary entry")}
              </span>
            </div>
          ))}
        </PopupSection>
      )}
      {expanded && content.construction && (
        <PopupSection title="Grammar pattern">
          <div className="grid grid-cols-[minmax(56px,auto)_minmax(0,1fr)] items-start gap-[10px]">
            <span className="popup-copy text-[14px] leading-[23px] [color:var(--popup-ink)] [font-family:var(--popup-reading-font)] [overflow-wrap:anywhere]">
              {content.construction.headword}
            </span>
            <span className="popup-copy text-[14px] leading-[23px] [color:var(--popup-ink)] [font-family:var(--popup-reading-font)] [overflow-wrap:anywhere]">
              {content.construction.gloss ??
                content.construction.definition ??
                "listed in the dictionary"}
            </span>
          </div>
        </PopupSection>
      )}
      {expanded && (content.other_entries ?? []).length > 0 && (
        <PopupSection title="Other entries">
          {(content.other_entries ?? []).map((other, index) => (
            <p
              className="popup-copy m-0 text-[14px] leading-[23px] [color:var(--popup-ink)] [font-family:var(--popup-reading-font)] [overflow-wrap:anywhere]"
              key={`${other.headword}-${index}`}
            >
              {[other.headword, other.part_of_speech, entryGloss(other)]
                .filter(Boolean)
                .join(" · ")}
            </p>
          ))}
        </PopupSection>
      )}
      {expanded && entry.vocabulary_level && (
        <p className="mt-4 mb-0 border-t pt-[10px] text-[12px] leading-5 [border-color:var(--popup-line)] [color:var(--popup-muted)] [font-family:var(--popup-display-font)]">
          Vocabulary level: {entry.vocabulary_level}
        </p>
      )}
    </div>
  );
}

function PrimarySense({
  sense,
  numbered,
}: {
  sense: PopupSense;
  numbered: boolean;
}) {
  const lead = sense.gloss || sense.definition || "";

  return (
      <div className="flex flex-col gap-[6px]">
      <div className="flex min-w-0 items-baseline gap-2">
        {numbered && (
          <span className="popup-meaning-index min-w-4 flex-none [color:var(--popup-translation)] [font-family:var(--popup-bold-font)]">
            1.
          </span>
        )}
        <div className="popup-meaning min-w-0 [color:var(--popup-translation)] [font-family:var(--popup-bold-font)] [overflow-wrap:anywhere]">
          {lead}
        </div>
      </div>
      {sense.gloss && sense.definition && (
        <p
          className={`popup-copy m-0 text-[14px] leading-[21px] [color:var(--popup-muted)] [font-family:var(--popup-reading-font)] [overflow-wrap:anywhere] ${numbered ? "ml-6" : ""}`}
        >
          {sense.definition}
        </p>
      )}
    </div>
  );
}

function PopupSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="mt-4 flex flex-col gap-2">
      <div className="mb-[2px] h-px bg-[var(--popup-line)]" />
      <h2 className="popup-section-title m-0 [color:var(--popup-muted)] [font-family:var(--popup-bold-font)]">
        {title}
      </h2>
      {children}
    </section>
  );
}

export function PopupNonSuccessContent({
  content,
}: {
  content: PopupContentData;
}) {
  return (
    <div className="flex flex-col gap-3 px-[18px] pt-4 pb-3 max-[361px]:px-4">
      {content.surface && (
        <h1 className="popup-headword m-0 pr-[30px] [color:var(--popup-ink)] [font-family:var(--popup-bold-font)] [overflow-wrap:anywhere]">
          {content.surface}
        </h1>
      )}
      <h2 className="popup-lookup-title m-0 text-[16px] leading-6 [color:var(--popup-ink)] [font-family:var(--popup-bold-font)]">
        {content.title || "Lookup unavailable"}
      </h2>
      {content.body && (
        <p className="popup-copy m-0 text-[14px] leading-[23px] [color:var(--popup-ink)] [font-family:var(--popup-reading-font)] [overflow-wrap:anywhere]">
          {content.body}
        </p>
      )}
      {content.tip && (
        <p className="m-0 text-[12px] leading-5 [color:var(--popup-muted)] [font-family:var(--popup-display-font)] [overflow-wrap:anywhere]">
          {content.tip}
        </p>
      )}
    </div>
  );
}
