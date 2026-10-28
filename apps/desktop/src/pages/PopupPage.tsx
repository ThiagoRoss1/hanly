import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type { DesktopPopupEvent } from "../contracts/desktop.ts";
import { PopupFooter } from "../components/popup/PopupFooter.tsx";
import {
  PopupNonSuccessContent,
  PopupSuccessContent,
} from "../components/popup/PopupContent.tsx";
import {
  COMPACT_POPUP_WIDTH,
  EXPANDED_POPUP_WIDTH,
  POPUP_MAX_HEIGHT,
  initiallyExpanded,
  maximumPopupWidth,
  numberValue,
  popupContent,
  popupFont,
  text,
} from "../components/popup/popupModel.ts";
import {
  desktopRequest,
  markFrontendReady,
} from "../services/desktopBridge.ts";
import { listenToDesktopEvents } from "../services/desktopEvents.ts";
import { normalizeDesktopError } from "../services/desktopBridgeCore.ts";

const POPUP_FRAME_CLASS =
  "popup-frame relative isolate flex max-h-[560px] max-w-[460px] flex-col overflow-hidden border-0 rounded-none bg-transparent p-[5px] shadow-none [color:var(--popup-ink)]";

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
      <main className={POPUP_FRAME_CLASS} role="alert">
        <div className="px-[21px] pt-[22px] pb-[22px]">
          <h1 className="popup-headword m-0 [color:var(--popup-ink)] [font-family:var(--popup-bold-font)]">
            Hanly
          </h1>
          <p className="m-0 text-[14px] leading-[23px] [color:var(--popup-ink)] [font-family:var(--popup-reading-font)] [overflow-wrap:anywhere]">
            {bridgeError}
          </p>
        </div>
      </main>
    );
  }

  return (
    <main
      aria-label="Hanly dictionary result"
      className={POPUP_FRAME_CLASS}
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
      <div className="popup-scroll min-h-0 max-h-none flex-[1_1_auto] overflow-x-hidden overflow-y-auto scroll-p-4">
        {success && entry ? (
          <>
            <PopupSuccessContent
              content={content}
              entry={entry}
              expanded={expanded}
            />
            {detailLevel === "full" && technical.length > 0 && (
              <section className="flex-none border-t px-[18px] pt-2 [border-color:var(--popup-line)]">
                <h2 className="popup-section-title mb-1 mt-0 [color:var(--popup-muted)] [font-family:var(--popup-bold-font)]">
                  Dictionary details
                </h2>
                <p className="m-0 text-[12px] leading-5 [color:var(--popup-muted)] [font-family:var(--popup-display-font)] [overflow-wrap:anywhere]">
                  {technical.join(" · ")}
                </p>
              </section>
            )}
          </>
        ) : (
          <PopupNonSuccessContent content={content} />
        )}
      </div>
      {(canExpand || (detailLevel === "basic" && technical.length > 0)) && (
        <PopupFooter
          content={content}
          detailLevel={detailLevel}
          expanded={expanded}
          canExpand={canExpand}
          senseCount={senses.length}
          onToggleExpanded={() => void toggleExpanded()}
        />
      )}
      <button
        aria-label="Close dictionary"
        className="popup-close absolute top-3 right-3 z-[2] grid h-7 w-7 place-items-center border-0 bg-transparent p-0 cursor-pointer hover:bg-[rgb(180_154_202_/_13%)]"
        onClick={() => void closePopup()}
        type="button"
      >
        <img
          alt=""
          className="block h-[22px] w-[22px] object-contain [image-rendering:pixelated] [filter:var(--popup-filter)]"
          src="/design/media/assets/panels/controls/close.png"
        />
      </button>
    </main>
  );
}
