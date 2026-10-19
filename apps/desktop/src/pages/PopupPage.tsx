import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import type {
  DesktopPopupEvent,
  PopupContent,
  PopupEntry,
  PopupPayload,
  PopupSense,
} from "../contracts/desktop.ts";
import {
  desktopRequest,
  markFrontendReady,
} from "../services/desktopBridge.ts";
import { listenToDesktopEvents } from "../services/desktopEvents.ts";
import { normalizeDesktopError } from "../services/desktopBridgeCore.ts";

function popupContent(payload: PopupPayload): PopupContent {
  return payload.content ?? payload;
}

function initiallyExpanded(payload: PopupPayload): boolean {
  if (typeof payload.expanded === "boolean") return payload.expanded;
  return payload.config?.popup_default_size === "expanded";
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function numberValue(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? value
    : fallback;
}

function maximumPopupWidth(): number {
  const available = window.screen.availWidth;
  return available > 0 ? Math.max(280, available - 16) : EXPANDED_POPUP_WIDTH;
}

type PopupFont = "pixel" | "normal";

function popupFont(payload: PopupPayload | undefined): PopupFont {
  if (!payload) return "pixel";

  const withFont = payload as PopupPayload & {
    popup_font?: unknown;
    config?: PopupPayload["config"] & { popup_font?: unknown };
  };
  const configured = withFont.config?.popup_font ?? withFont.popup_font;

  return configured === "normal" ? "normal" : "pixel";
}

function entryGloss(entry: PopupEntry): string {
  const sense = entry.senses?.find((item) => item.gloss || item.definition);
  return text(sense?.gloss || sense?.definition || entry.definitions?.[0]);
}

/** The card's own ceiling, as `.popup-frame` declares it. */
const POPUP_MAX_HEIGHT = 560;
const COMPACT_POPUP_WIDTH = 380;
const EXPANDED_POPUP_WIDTH = 460;

function wordTypes(raw?: string | null): [string, string] {
  const pairs: Array<[string, string]> = [
    ["명사", "Noun"],
    ["대명사", "Pronoun"],
    ["동사", "Verb"],
    ["형용사", "Adjective"],
    ["부사", "Adverb"],
    ["관형사", "Determiner"],
    ["수사", "Numeral"],
    ["조사", "Particle"],
    ["감탄사", "Interjection"],
    ["의존 명사", "Bound noun"],
  ];
  const normalized = (raw ?? "").replaceAll(" ", "").toLowerCase();

  return (
    pairs.find((pair) =>
      pair.some((name) => name.replaceAll(" ", "").toLowerCase() === normalized),
    ) ?? [raw ?? "", ""]
  );
}

export function PopupPage() {
  const [current, setCurrent] = useState<Extract<
    DesktopPopupEvent,
    { type: "popup" }
  > | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [bridgeError, setBridgeError] = useState("");
  // The height the native host found beside this answer's word; the card is
  // capped to it and scrolls, so it never slides under the Dock or the word.
  const [room, setRoom] = useState<{ sequence: number; height: number } | null>(
    null,
  );
  const currentSequence = useRef(-1);
  const geometrySent = useRef("");
  const cardRef = useRef<HTMLElement | null>(null);
  const retryTimer = useRef<number | null>(null);
  const roomRef = useRef(room);
  roomRef.current = room;

  useEffect(() => {
    let active = true;
    let unlisten: (() => void) | null = null;
    void listenToDesktopEvents({
      onPopup: (event) => {
        if (event.sequence < currentSequence.current) return;
        if (event.sequence > currentSequence.current) {
          currentSequence.current = event.sequence;
          geometrySent.current = "";
          if (retryTimer.current !== null) window.clearTimeout(retryTimer.current);
          retryTimer.current = null;
          setBridgeError("");
          if (event.type === "popup")
            setExpanded(initiallyExpanded(event.payload));
        }
        setCurrent(event.type === "popup" ? event : null);
      },
    })
      .then(async (dispose) => {
        if (!active) {
          dispose();
          return;
        }
        unlisten = dispose;
        await markFrontendReady("popup");
      })
      .catch((reason: unknown) => {
        if (active) setBridgeError(normalizeDesktopError(reason).message);
      });
    return () => {
      active = false;
      unlisten?.();
    };
  }, []);

  useEffect(() => {
    // The popup is never key, so its context menu is the only way to copy a
    // selection. Elsewhere WebKit's menu offers Reload, which would blank the
    // card, and its modal tracking would hold the native event loop.
    const onContextMenu = (event: MouseEvent) => {
      if (!window.getSelection()?.toString()) event.preventDefault();
    };
    window.addEventListener("contextmenu", onContextMenu);
    return () => window.removeEventListener("contextmenu", onContextMenu);
  }, []);

  const reportGeometry = useCallback(function reportGeometry(sequence: number, attempt = 0) {
    if (currentSequence.current !== sequence) return;
    const card = cardRef.current;
    if (!card) return;
    const rect = card.getBoundingClientRect();
    const width = Math.max(1, Math.ceil(rect.width));
    const height = Math.max(1, Math.ceil(rect.height));
    const measured = roomRef.current?.sequence === sequence;
    const method = measured ? "popup_geometry" : "popup_measure";
    const key = `${sequence}:${method}:${width}:${height}`;
    if (geometrySent.current === key) return;
    geometrySent.current = key;
    void desktopRequest<{ room?: unknown }>(method, { sequence, width, height })
      .then((reply) => {
        if (currentSequence.current !== sequence) return;
        const available = reply?.room;
        if (!measured) {
          if (typeof available !== "number" || !Number.isFinite(available) || available <= 0) {
            throw new Error("Hanly returned invalid popup layout bounds.");
          }
          setRoom({ sequence, height: available });
        }
      })
      .catch((reason: unknown) => {
        if (currentSequence.current !== sequence || geometrySent.current !== key) return;
        geometrySent.current = "";
        if (attempt === 0) {
          retryTimer.current = window.setTimeout(() => reportGeometry(sequence, 1), 80);
        } else {
          setBridgeError(normalizeDesktopError(reason).message);
        }
      });
  }, []);

  useEffect(() => () => {
    if (retryTimer.current !== null) window.clearTimeout(retryTimer.current);
  }, []);

  const payload = current?.payload;
  const content = payload ? popupContent(payload) : null;
  const sequence = current?.sequence;
  const entry = content?.entry ?? null;
  const senses = entry?.senses ?? [];
  const otherEntries = content?.other_entries ?? [];
  const technical = content?.technical_lines ?? [];
  const detailLevel =
    payload?.technical_details ?? payload?.config?.technical_details ?? "off";
  const theme = payload?.theme ?? payload?.config?.theme ?? "system";
  const font = popupFont(payload);
  const width = Math.min(
    EXPANDED_POPUP_WIDTH,
    maximumPopupWidth(),
    Math.max(
      expanded ? EXPANDED_POPUP_WIDTH : COMPACT_POPUP_WIDTH,
      numberValue(
        payload?.size?.width,
        expanded ? EXPANDED_POPUP_WIDTH : COMPACT_POPUP_WIDTH,
      ),
    ),
  );
  const success = text(content?.status).toLowerCase() === "success";
  const hasAnalysis = Boolean(
    content?.analysis?.length ||
      content?.components?.length ||
      content?.construction ||
      content?.source ||
      (content?.surface && content.lemma && content.surface !== content.lemma),
  );
  const canExpand =
    success &&
    (expanded ||
      senses.length > 2 ||
      otherEntries.length > 0 ||
      hasAnalysis ||
      Boolean(entry?.vocabulary_level));

  useLayoutEffect(() => {
    document.documentElement.dataset.popup = "true";
    document.documentElement.dataset.popupFont = font;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.mode =
        theme === "system" ? (media.matches ? "dark" : "light") : theme;
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [font, theme]);

  useLayoutEffect(() => {
    if (sequence === undefined || !content) return;
    // Hidden webviews may throttle animation frames. Measure the committed DOM
    // directly. Native measurement supplies the cap before a painted frame
    // is presented, so the first visible card already fits the available room.
    reportGeometry(sequence);
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => reportGeometry(sequence));
    if (cardRef.current) observer?.observe(cardRef.current);
    return () => {
      observer?.disconnect();
    };
  }, [content, expanded, reportGeometry, room, sequence]);

  useLayoutEffect(() => {
    if (sequence === undefined || !content) return;
    let active = true;
    const fontsReady = document.fonts?.ready;

    void fontsReady?.then(() => {
      if (
        !active ||
        currentSequence.current !== sequence ||
        roomRef.current?.sequence !== sequence
      ) {
        return;
      }

      geometrySent.current = "";
      reportGeometry(sequence);
    });

    return () => {
      active = false;
    };
  }, [content, font, reportGeometry, sequence]);

  async function closePopup() {
    if (sequence === undefined) return;
    await desktopRequest("popup_close", { sequence }).catch((reason: unknown) =>
      setBridgeError(normalizeDesktopError(reason).message),
    );
  }

  async function toggleExpanded() {
    if (sequence === undefined) return;
    const next = !expanded;
    await desktopRequest("popup_expand", { sequence, expanded: next }).catch(
      (reason: unknown) => {
        if (currentSequence.current === sequence)
          setBridgeError(normalizeDesktopError(reason).message);
      },
    );
  }

  if (!current || !content) {
    if (!bridgeError) return null;
    return (
      <main className="popup-frame popup-connection-error" role="alert">
        <div className="popup-content">
          <h1 className="popup-title">Hanly</h1>
          <p className="popup-secondary">{bridgeError}</p>
        </div>
      </main>
    );
  }

  return (
    <main
      aria-label="Hanly dictionary result"
      className="popup-frame"
      data-expanded={expanded}
      data-success={success}
      ref={cardRef}
      style={{
        width: `${width}px`,
        maxHeight:
          room && room.sequence === sequence
            ? `${Math.min(POPUP_MAX_HEIGHT, Math.floor(room.height))}px`
            : undefined,
      }}
    >
      <div className="popup-scroll">
        {success && entry ? (
          <>
            <SuccessContent
              content={content}
              entry={entry}
              expanded={expanded}
            />
            {detailLevel === "full" && technical.length > 0 && (
              <section className="popup-details">
                <h2 className="popup-section">Dictionary details</h2>
                <p className="popup-muted">{technical.join(" · ")}</p>
              </section>
            )}
          </>
        ) : (
          <NonSuccessContent content={content} />
        )}
      </div>
      {(canExpand || (detailLevel === "basic" && technical.length > 0)) && (
        <footer className="popup-footer">
          {detailLevel === "basic" && technical.length > 0 && (
            <span className="popup-muted popup-footer-detail">
              {technical.join(" · ")}
            </span>
          )}
          <span className="popup-more">
            {!expanded && senses.length > 2
              ? "+" + String(senses.length - 2) + " more meanings"
              : ""}
          </span>
          <span className="popup-footer-spacer" />
          {canExpand && (
            <button
              aria-expanded={expanded}
              className="popup-button popup-details-button"
              onClick={() => void toggleExpanded()}
              type="button"
            >
              <span>{expanded ? "Less detail" : "Details"}</span>
              <img
                alt=""
                className="popup-details-icon"
                src={
                  expanded
                    ? "/design/media/assets/icons/custom/icon-details-minus.svg"
                    : "/design/media/assets/icons/custom/icon-details-plus.svg"
                }
              />
            </button>
          )}
        </footer>
      )}
      <button
        aria-label="Close dictionary"
        className="popup-close"
        onClick={() => void closePopup()}
        type="button"
      >
        <img alt="" src="/design/media/assets/panels/controls/close.png" />
      </button>
    </main>
  );
}

function SuccessContent({
  content,
  entry,
  expanded,
}: {
  content: PopupContent;
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
    <div className="popup-content">
      <header className="popup-entry-head">
        <h1 className="popup-title" lang="ko">{entry.headword}</h1>
        {entry.hanja && <span className="popup-hanja">{entry.hanja}</span>}
      </header>
      {koreanType && (
        <div className="popup-type-row">
          <span className="popup-chip" lang="ko">{koreanType}</span>
          {englishType && <span className="popup-chip" lang="en">{englishType}</span>}
        </div>
      )}
      {primarySense && (
        <div className="popup-senses">
          <PrimarySense sense={primarySense} numbered={senses.length > 1} />
          {visibleSenses.slice(1).map((sense, index) => (
            <div
              className="popup-numbered-sense"
              key={`${sense.definition ?? sense.gloss ?? "sense"}-${index}`}
            >
              <div className="popup-meaning-line">
                <span className="popup-number">{index + 2}.</span>
                <div className="popup-secondary-gloss">
                  {sense.gloss || sense.definition}
                </div>
              </div>
              {sense.gloss && sense.definition && (
                <p className="popup-muted popup-sense-description">
                  {sense.definition}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
      {visibleSenses.length === 0 && entry.definitions?.[0] && (
        <div className="popup-primary">{entry.definitions[0]}</div>
      )}
      {expanded && (analysis.length > 0 || changed || source) && (
        <PopupSection title="Read as">
          <div className="popup-read-as">
          {changed && (
            <p className="popup-part">
              {content.surface} <span aria-hidden="true">→</span>{" "}
              {content.lemma}
            </p>
          )}
          {source && <span className="popup-analysis-source">{source}</span>}
          </div>
          {analysis.length > 0 && (
            <p className="popup-secondary">
              {analysis.map((piece) => piece.text).join("  +  ")}
            </p>
          )}
          {analysis.some((piece) => piece.role) && (
            <p className="popup-muted">
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
              className="popup-component"
              key={`${component.surface}-${index}`}
            >
              <span
                className={
                  component.selected
                    ? "popup-part popup-part-selected"
                    : "popup-part"
                }
              >
                {component.surface}
              </span>
              <span
                className={
                  component.grammatical ? "popup-muted" : "popup-secondary"
                }
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
          <div className="popup-component">
            <span className="popup-part">{content.construction.headword}</span>
            <span className="popup-secondary">
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
            <p className="popup-secondary" key={`${other.headword}-${index}`}>
              {[other.headword, other.part_of_speech, entryGloss(other)]
                .filter(Boolean)
                .join(" · ")}
            </p>
          ))}
        </PopupSection>
      )}
      {expanded && entry.vocabulary_level && (
        <p className="popup-entry-metadata">
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
    <div className="popup-primary-sense" data-numbered={numbered}>
      <div className="popup-meaning-line">
        {numbered && <span className="popup-number popup-number-primary">1.</span>}
        <div className="popup-primary">{lead}</div>
      </div>
      {sense.gloss && sense.definition && (
        <p className="popup-primary-note popup-sense-description">
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
    <section className="popup-section-block">
      <div className="popup-divider" />
      <h2 className="popup-section">{title}</h2>
      {children}
    </section>
  );
}

function NonSuccessContent({ content }: { content: PopupContent }) {
  return (
    <div className="popup-content popup-non-success">
      {content.surface && (
        <h1 className="popup-title popup-surface">{content.surface}</h1>
      )}
      <h2 className="popup-sense-title">
        {content.title || "Lookup unavailable"}
      </h2>
      {content.body && <p className="popup-secondary">{content.body}</p>}
      {content.tip && <p className="popup-muted">{content.tip}</p>}
    </div>
  );
}
