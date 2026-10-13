import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type {
  DesktopPopupEvent,
  PopupContent,
  PopupEntry,
  PopupPayload,
  PopupSense,
} from "../contracts/desktop.ts";
import { desktopRequest, markFrontendReady } from "../services/desktopBridge.ts";
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
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : fallback;
}

function entryGloss(entry: PopupEntry): string {
  const sense = entry.senses?.find((item) => item.gloss || item.definition);
  return text(sense?.gloss || sense?.definition || entry.definitions?.[0]);
}

export function PopupPage() {
  const [current, setCurrent] = useState<Extract<DesktopPopupEvent, { type: "popup" }> | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [bridgeError, setBridgeError] = useState("");
  const currentSequence = useRef(-1);
  const geometrySent = useRef("");
  const cardRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    let active = true;
    let unlisten: (() => void) | null = null;
    void listenToDesktopEvents({
      onPopup: (event) => {
        if (event.sequence < currentSequence.current) return;
        if (event.sequence > currentSequence.current) {
          currentSequence.current = event.sequence;
          geometrySent.current = "";
          if (event.type === "popup") setExpanded(initiallyExpanded(event.payload));
        }
        setCurrent(event.type === "popup" ? event : null);
      },
    }).then(async (dispose) => {
      if (!active) {
        dispose();
        return;
      }
      unlisten = dispose;
      await markFrontendReady("popup");
    }).catch((reason: unknown) => {
      if (active) setBridgeError(normalizeDesktopError(reason).message);
    });
    return () => {
      active = false;
      unlisten?.();
    };
  }, []);

  const reportGeometry = useCallback((sequence: number) => {
    const frame = window.requestAnimationFrame(() => {
      if (currentSequence.current !== sequence) return;
      const card = cardRef.current;
      if (!card) return;
      const rect = card.getBoundingClientRect();
      const width = Math.max(1, Math.round(rect.width));
      const height = Math.max(1, Math.round(rect.height));
      const key = `${sequence}:${width}:${height}`;
      if (geometrySent.current === key) return;
      geometrySent.current = key;
      void desktopRequest("popup_geometry", { sequence, width, height }).catch(() => undefined);
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  const payload = current?.payload;
  const content = payload ? popupContent(payload) : null;
  const sequence = current?.sequence;
  const entry = content?.entry ?? null;
  const senses = entry?.senses ?? [];
  const otherEntries = content?.other_entries ?? [];
  const technical = content?.technical_lines ?? [];
  const detailLevel = payload?.technical_details ?? payload?.config?.technical_details ?? "off";
  const theme = payload?.theme ?? payload?.config?.theme ?? "system";
  const width = Math.min(460, Math.max(300, numberValue(payload?.size?.width, 340)));
  const success = text(content?.status).toLowerCase() === "success";
  const canExpand = success && (expanded || senses.length > 2 || otherEntries.length > 0 || (content?.analysis?.length ?? 0) > 0);

  useEffect(() => {
    document.documentElement.dataset.popup = "true";
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.mode = theme === "system" ? (media.matches ? "dark" : "light") : theme;
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);

  useLayoutEffect(() => {
    if (sequence === undefined || !content) return;
    const cancelFrame = reportGeometry(sequence);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => reportGeometry(sequence));
    if (cardRef.current) observer?.observe(cardRef.current);
    return () => {
      cancelFrame();
      observer?.disconnect();
    };
  }, [content, expanded, reportGeometry, sequence]);

  async function closePopup() {
    if (sequence === undefined) return;
    await desktopRequest("popup_close", { sequence }).catch((reason: unknown) => setBridgeError(normalizeDesktopError(reason).message));
  }

  async function toggleExpanded() {
    if (sequence === undefined) return;
    const next = !expanded;
    setExpanded(next);
    await desktopRequest("popup_expand", { sequence, expanded: next }).catch((reason: unknown) => {
      setExpanded(!next);
      setBridgeError(normalizeDesktopError(reason).message);
    });
  }

  if (!current || !content) {
    if (!bridgeError) return null;
    return <main className="popup-frame popup-connection-error" role="alert"><div className="popup-content"><h1 className="popup-title">Hanly</h1><p className="popup-secondary">{bridgeError}</p></div></main>;
  }

  return (
    <main aria-label="Hanly dictionary result" className="popup-frame" ref={cardRef} style={{ width: `${width}px` }}>
      <div className="popup-scroll">
        {success && entry ? <SuccessContent content={content} entry={entry} expanded={expanded} /> : <NonSuccessContent content={content} />}
      </div>
      {detailLevel === "full" && technical.length > 0 && <section className="popup-details"><div className="popup-section">Details</div><p className="popup-muted">{technical.join(" · ")}</p></section>}
      <footer className="popup-footer">
        {detailLevel === "basic" && technical.length > 0 && <span className="popup-muted popup-footer-detail">{technical.join(" · ")}</span>}
        <span className="popup-footer-spacer" />
        {canExpand && <button className="popup-button popup-size" onClick={() => void toggleExpanded()} type="button">{expanded ? "Collapse" : "Expand"}</button>}
        <button className="popup-button" onClick={() => void closePopup()} type="button">Close</button>
      </footer>
    </main>
  );
}

function SuccessContent({ content, entry, expanded }: { content: PopupContent; entry: PopupEntry; expanded: boolean }) {
  const senses = entry.senses ?? [];
  const visibleSenses = expanded ? senses : senses.slice(0, 2);
  const primarySense = visibleSenses[0];
  const analysis = content.analysis ?? [];
  const changed = Boolean(content.surface && content.lemma && content.surface !== content.lemma);
  const metadata = [content.source?.toUpperCase(), entry.vocabulary_level].filter(Boolean).join(" · ");
  return (
    <div className="popup-content">
      <header className="popup-entry-head"><h1 className="popup-title">{entry.headword}</h1>{entry.hanja && <span className="popup-hanja">{entry.hanja}</span>}</header>
      {(entry.part_of_speech || metadata) && <div className="popup-meta-row">{entry.part_of_speech && <span className="popup-chip">{entry.part_of_speech}</span>}{metadata && <span className="popup-meta">{metadata}</span>}</div>}
      {primarySense && <div className="popup-senses"><PrimarySense sense={primarySense} />{visibleSenses.slice(1).map((sense, index) => <div className="popup-numbered-sense" key={`${sense.definition ?? sense.gloss ?? "sense"}-${index}`}><span className="popup-number">{index + 2}</span><div>{sense.gloss && <div className="popup-secondary">{sense.gloss}</div>}{sense.definition && <div className="popup-muted">{sense.definition}</div>}</div></div>)}</div>}
      {visibleSenses.length === 0 && entry.definitions?.[0] && <div className="popup-primary">{entry.definitions[0]}</div>}
      {(analysis.length > 0 || changed) && <PopupSection title={expanded ? "Word analysis" : "Read as"}>{changed && <p className="popup-part">{content.surface} <span aria-hidden="true">→</span> {content.lemma}</p>}{analysis.length > 0 && <p className="popup-secondary">{analysis.map((piece) => piece.text).join("  +  ")}</p>}{analysis.some((piece) => piece.role) && <p className="popup-muted">{analysis.map((piece) => piece.role).filter(Boolean).join(" · ")}</p>}</PopupSection>}
      {(content.components ?? []).length > 0 && <PopupSection title="How this form is built">{(content.components ?? []).map((component, index) => <div className="popup-component" key={`${component.surface}-${index}`}><span className={component.selected ? "popup-part popup-part-selected" : "popup-part"}>{component.surface}</span><span className={component.grammatical ? "popup-muted" : "popup-secondary"}>{component.gloss ?? (component.grammatical ? "grammatical" : "no dictionary entry")}</span></div>)}</PopupSection>}
      {expanded && (content.other_entries ?? []).length > 0 && <PopupSection title="Other entries">{(content.other_entries ?? []).map((other, index) => <p className="popup-secondary" key={`${other.headword}-${index}`}>{[other.headword, other.part_of_speech, entryGloss(other)].filter(Boolean).join(" · ")}</p>)}</PopupSection>}
    </div>
  );
}

function PrimarySense({ sense }: { sense: PopupSense }) {
  const lead = sense.gloss || sense.definition || "";
  return <div className="popup-primary-sense"><div className="popup-primary">{lead}</div>{sense.gloss && sense.definition && <div className="popup-primary-note">{sense.definition}</div>}</div>;
}

function PopupSection({ title, children }: { title: string; children: ReactNode }) {
  return <section className="popup-section-block"><div className="popup-divider" /><h2 className="popup-section">{title}</h2>{children}</section>;
}

function NonSuccessContent({ content }: { content: PopupContent }) {
  return <div className="popup-content popup-non-success">{content.surface && <h1 className="popup-title popup-surface">{content.surface}</h1>}<h2 className="popup-sense-title">{content.title || "Lookup unavailable"}</h2>{content.body && <p className="popup-secondary">{content.body}</p>}{content.tip && <p className="popup-muted">{content.tip}</p>}</div>;
}
