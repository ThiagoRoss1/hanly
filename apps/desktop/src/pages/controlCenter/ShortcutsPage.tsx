import { useEffect, useState } from "react";
import type { HanlyState } from "../../contracts/desktop.ts";
import { PixelButton } from "../../components/PixelButton.tsx";
import { TargetOption } from "../../components/controlCenter/Controls.tsx";
import {
  HOTKEYS,
  errorText,
  sharesAppShortcut,
  formatHotkey,
  hotkeyFromKeyboardEvent,
} from "./helpers.ts";
import { settingPendingKey } from "./helpers.ts";
import type { IsPending, RunCommand } from "./types.ts";

export function ShortcutsPage({
  state,
  isPending,
  run,
  saveSettings,
}: {
  state: HanlyState;
  isPending: IsPending;
  run: RunCommand;
  saveSettings: (changes: Record<string, unknown>) => Promise<unknown>;
}) {
  const [recording, setRecording] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState("");
  useEffect(() => {
    if (!recording) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Tab" ||
          (event.key === "Enter" && event.target instanceof HTMLButtonElement &&
           event.target.getAttribute("aria-label")?.startsWith("Save "))) return;
      event.preventDefault();
      if (event.key === "Escape") {
        setRecording(null);
        return;
      }
      const binding = hotkeyFromKeyboardEvent(event);
      if (!binding) return;
      setDraft(binding);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [recording]);

  async function confirmShortcut() {
    if (!recording || !draft) return;
    setError("");
    try {
      const result = recording === "hotkey"
        ? await run("set_hotkey", { hotkey: draft })
        : await saveSettings({ [recording]: draft });
      if (result !== undefined) setRecording(null);
    } catch (reason) {
      setError(errorText(reason));
    }
  }

  const registered = state.runtime.hotkeys ?? {};
  const prepared = (state.app.state ?? "new") !== "new";
  return (
    <div className="page flex max-w-none flex-col gap-6">
      {HOTKEYS.map((item, index) => {
        const stored = String(state.config[item.id] ?? "");
        const live = registered[item.action] ?? "";
        const isRecording = recording === item.id;
        const note =
          !isRecording &&
          (!stored
            ? {
                tone: "warn",
                title: "Unassigned.",
                text: "No free combination was left for this action. Choose one.",
              }
            : live && live !== stored
              ? {
                  tone: "warn",
                  title: `Registered as ${live}.`,
                  text: "The stored shortcut was not the one the system accepted.",
                }
              : prepared && stored && !live
                ? {
                    tone: "bad",
                    title: "Not registered.",
                    text: "Another application may already own this combination, so your keyboard does not do this yet.",
                  }
                : sharesAppShortcut(stored)
                  ? {
                      tone: "warn",
                      title: "Used by other apps.",
                      text: "Most apps already use this combination, and Hanly takes it from all of them while it runs. Add another modifier key.",
                    }
                  : null);
        return (
          <section
            className="panel relative min-w-0"
            data-recording={isRecording}
            data-rise={index + 1}
            key={item.id}
          >
            <div className="shortcut-row relative flex min-h-[120px] flex-wrap items-center gap-[18px] px-[26px] pt-[50px] pb-[22px]">
              <div className="shortcut-text min-w-[160px] flex-1">
                <div className="shortcut-name">{item.name}</div>
                <div className="shortcut-hint mt-0 max-w-[300px] text-[13px] leading-5">{item.hint}</div>
              </div>
              <div
                aria-label={`${item.name} shortcut`}
                className="shortcut-keys flex min-h-10 flex-none flex-wrap items-center gap-1.5"
              >
                {isRecording ? (
                  <span className="key" data-kind="recording">
                    {draft ? formatHotkey(draft).join(" + ") : "Press keys… Esc cancels"}
                  </span>
                ) : !stored ? (
                  <span className="key" data-kind="empty">
                    unassigned
                  </span>
                ) : (
                  formatHotkey(stored).map((key, keyIndex) => (
                    <span className="key" key={`${key}-${keyIndex}`}>
                      {key}
                    </span>
                  ))
                )}
              </div>
              {isRecording && (
                <PixelButton className="btn btn-sm" aria-label={`Save ${item.name} shortcut`}
                  disabled={!draft || isPending(item.id === "hotkey" ? "set_hotkey" : settingPendingKey(item.id))}
                  onClick={() => void confirmShortcut()} type="button">Save</PixelButton>
              )}
              <PixelButton
                aria-label={`${isRecording ? "Cancel" : stored ? "Change" : "Assign"} ${item.name} shortcut`}
                icon={!isRecording ? "/design/media/assets/icons/v2/icon-edit.png" : undefined}
                className={`btn btn-sm btn-fixed shortcut-edit${!stored && !isRecording ? " btn-primary" : ""}`}
                disabled={isPending(
                  item.id === "hotkey" ? "set_hotkey" : settingPendingKey(item.id),
                )}
                onClick={() => { setDraft(""); setError(""); setRecording(isRecording ? null : item.id); }}
                type="button"
              >

                {isRecording ? "Cancel" : stored ? "Change" : "Assign"}
              </PixelButton>
            </div>
            {note && (
              <div className="shortcut-note" data-tone={note.tone}>
                <span aria-hidden="true" className="dot" />
                <span>
                  <span className="shortcut-note-title">{note.title}</span>{" "}
                  {note.text}
                </span>
              </div>
            )}
          </section>
        );
      })}
      {error && (
        <div className="banner" data-tone="bad" role="alert">
          {error}
        </div>
      )}
      <section className="panel relative min-w-0" data-rise="4">
        <div className="panel-head relative flex min-h-[104px] items-center gap-5 px-[26px] pt-[50px] pb-5">
          <div className="min-w-0">
            <h2 className="panel-title absolute inset-x-[22px] top-0 m-0 flex h-[34px] items-center justify-center text-center">Automatic hover</h2>
            <p className="panel-note m-0 max-w-[540px] text-[13px] leading-5">
              Choose when the Push to Hover action is active.
            </p>
          </div>
        </div>
        <div className="panel-rows flex flex-col px-4 pb-4" role="radiogroup">
          {[
            {
              value: "push_to_hover",
              label: "Only while held",
              desc: "Hover reads while the Push to Hover shortcut is held down.",
            },
            {
              value: "always_active",
              label: "Whenever capture is running",
              desc: "Hover reads for the whole capture session, subject to permissions.",
            },
          ].map((mode) => (
            <TargetOption
              key={mode.value}
              selected={state.config.hover_activation === mode.value}
              disabled={isPending(settingPendingKey("hover_activation"))}
              label={mode.label}
              detail={mode.desc}
              onSelect={() =>
                void saveSettings({ hover_activation: mode.value })
              }
            />
          ))}
        </div>
      </section>
    </div>
  );
}
