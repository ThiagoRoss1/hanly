import { useEffect, useRef, type KeyboardEvent } from "react";
import { PixelButton } from "../PixelButton.tsx";
import { Mascot } from "../village/Mascot.tsx";
import { titleCase, valueText } from "../../pages/controlCenter/helpers.ts";

export function Brand() {
  return (
    <div className="brand relative z-[1] mt-[38px] mb-[14px] flex min-h-16 flex-none items-center gap-3 bg-transparent p-0">
      <BrandMark />
      <div className="brand-words min-w-0">
        <div className="brand-name text-2xl leading-[30px] tracking-normal">Hanly</div>
        <div className="brand-sub mt-0.5 text-[11px] leading-[18px] font-normal tracking-normal normal-case">
          Control Center
        </div>
      </div>
    </div>
  );
}

export function BrandMark() {
  return (
    <span
      className="brand-mark relative block h-16 w-16 shrink-0"
    >
      <img
        aria-hidden="true"
        alt=""
        className="absolute inset-0 h-full w-full object-contain [image-rendering:pixelated]"
        src="/design/media/assets/icons/custom/hanly-app.png"
      />
    </span>
  );
}

export function LiveCard({
  activity,
  engine,
  runtime,
  version,
  detail,
}: {
  activity: string;
  engine: string;
  runtime: string;
  version?: string | null;
  detail?: string;
}) {
  const tone =
    activity === "running" ? "ok" : activity === "error" ? "bad" : "";
  const runtimeTone =
    runtime === "ready" ? "ok" : runtime === "failed" ? "bad" : "warn";
  const engineTone =
    engine === "ready" ? "ok" : engine === "error" ? "bad" : "";
  return (
    <div className="live-card relative isolate grid min-h-[164px] grid-cols-[80px_minmax(0,1fr)] grid-rows-[72px_auto_auto] content-center gap-x-2 gap-y-2 p-5" title={[activity, `Runtime ${runtime}`, `Engine ${engine}`, detail].filter(Boolean).join(" · ")} aria-label={`${activity} · Runtime ${runtime} · Engine ${engine}`}>
      <Mascot activity={activity} />
      <div className="live-head col-start-2 row-start-1 flex min-w-0 items-center self-center gap-[7px]">
        <span
          aria-hidden="true"
          className="dot h-2 w-2 shrink-0"
          data-tone={tone || undefined}
        />
        <span className="live-label text-xs leading-[18px]">{titleCase(activity, "Preparing")}</span>
      </div>
      {activity !== "stopped" && detail && (
        <div className="live-detail col-span-full row-start-2 min-w-0 text-[10px] leading-[14px] [overflow-wrap:anywhere]">{detail}</div>
      )}
      <div aria-live="polite" className="live-facts col-span-full row-start-3 grid min-w-0 grid-cols-3 gap-1 text-[10px]" role="status">
        <div className="live-fact flex min-w-0 flex-col gap-0.5" data-tone={runtimeTone}>
          <span className="text-[10px] leading-[14px] text-[var(--skin-ink-muted)]">runtime</span>
          <span className="truncate text-[10px] leading-[14px] font-bold text-[var(--skin-ink)]">{valueText(runtime)}</span>
        </div>
        <div className="live-fact flex min-w-0 flex-col gap-0.5" data-tone={engineTone}>
          <span className="text-[10px] leading-[14px] text-[var(--skin-ink-muted)]">engine</span>
          <span className="truncate text-[10px] leading-[14px] font-bold text-[var(--skin-ink)]">{valueText(engine)}</span>
        </div>
        {version && (
          <div className="live-fact flex min-w-0 flex-col gap-0.5">
            <span className="text-[10px] leading-[14px] text-[var(--skin-ink-muted)]">version</span>
            <span className="truncate text-[10px] leading-[14px] font-bold text-[var(--skin-ink)]">{version}</span>
          </div>
        )}
      </div>
    </div>
  );
}

export function LoadingPanel({ message }: { message: string }) {
  return (
    <section className="panel relative min-w-0">
      <div className="panel-head relative flex min-h-[104px] items-center gap-5 px-[26px] pt-[50px] pb-5">
        <h2 className="panel-title absolute inset-x-[22px] top-0 m-0 flex h-[34px] items-center justify-center text-center">Hanly</h2>
      </div>
      <div className="panel-rows flex flex-col px-4 pb-4">
        <div className="readiness-row flex min-h-11 flex-wrap items-center gap-3 py-3">
          <span className="readiness-detail min-w-[110px] flex-1 text-[13px] leading-5">{message}</span>
        </div>
      </div>
    </section>
  );
}

export function CaptureChoiceDialog({
  busy,
  onCancel,
  onChooseMonitor,
  onChooseRegion,
}: {
  busy: boolean;
  onCancel: () => void;
  onChooseMonitor: () => void;
  onChooseRegion: () => void;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const previousFocus = document.activeElement;
    dialogRef.current?.focus();

    return () => {
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) {
        previousFocus.focus();
      }
    };
  }, []);

  return (
    <div
      className="choice-backdrop fixed inset-0 z-20 grid place-items-center overflow-auto bg-[rgb(24_18_36_/_38%)] p-3.5 backdrop-blur-[2px]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <section
        aria-labelledby="capture-choice-title"
        aria-modal="true"
        className="choice-dialog panel max-h-[calc(100vh-28px)] w-[min(440px,100%)] max-w-full overflow-y-auto px-[26px] pt-[50px] pb-[26px]"
        onKeyDown={(event) => {
          if (event.key === "Escape") onCancel();
          if (event.key === "Tab") retainDialogFocus(event);
        }}
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
      >
        <h2 className="panel-title" id="capture-choice-title">
          Where should Hanly read?
        </h2>
        <p className="panel-note">
          Choose the area Hanly should watch. This is saved as a setting.
        </p>
        <div className="choice-actions mt-[22px] flex flex-wrap justify-end gap-2">
          <PixelButton
            className="btn"
            disabled={busy}
            onClick={onChooseMonitor}
            type="button"
          >
            Whole monitor
          </PixelButton>
          <PixelButton
            className="btn btn-primary"
            disabled={busy}
            onClick={onChooseRegion}
            type="button"
          >
            Select an area
          </PixelButton>
          <PixelButton
            className="btn btn-quiet"
            disabled={busy}
            onClick={onCancel}
            type="button"
          >
            Cancel
          </PixelButton>
        </div>
      </section>
    </div>
  );
}

function retainDialogFocus(event: KeyboardEvent<HTMLElement>) {
  const buttons = event.currentTarget.querySelectorAll<HTMLButtonElement>(
    "button:not(:disabled)",
  );
  const first = buttons[0];
  const last = buttons[buttons.length - 1];
  const active = document.activeElement;
  if (!first || !last) {
    event.preventDefault();
    return;
  }

  if (event.shiftKey && (active === first || active === event.currentTarget)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
  }
}
