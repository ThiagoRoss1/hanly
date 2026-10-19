import type { HanlyState } from "../../contracts/desktop.ts";
import { PixelButton } from "../../components/PixelButton.tsx";
import { settingPendingKey } from "./helpers.ts";
import type { IsPending } from "./types.ts";

export function AppearancePage({
  state,
  isPending,
  saveSettings,
}: {
  state: HanlyState;
  isPending: IsPending;
  saveSettings: (changes: Record<string, unknown>) => Promise<unknown>;
}) {
  const config = state.config;
  const groups = [
    {
      key: "sidebar_layout",
      label: "Navigation",
      note: "Use a compact rail without resizing the window.",
      options: [
        ["normal", "Normal"],
        ["compact", "Compact"],
      ],
    },
    {
      key: "theme",
      label: "Theme",
      note: "System follows the desktop setting.",
      options: [
        ["system", "System"],
        ["light", "Light"],
        ["dark", "Dark"],
      ],
    },
    {
      key: "popup_font",
      label: "Popup typeface",
      note: "Choose crisp standard text or the original pixel lettering.",
      options: [
        ["pixel", "Pixel"],
        ["normal", "Normal"],
      ],
    },
    {
      key: "popup_default_size",
      label: "Default popup size",
      note: "How each new dictionary popup opens.",
      options: [
        ["compact", "Compact"],
        ["expanded", "Expanded"],
      ],
    },
    {
      key: "technical_details",
      label: "Technical details",
      note: "Off keeps the popup focused on reading.",
      options: [
        ["off", "Off"],
        ["basic", "Basic"],
        ["full", "Full"],
      ],
    },
  ] as const;

  return (
    <div className="page flex max-w-none flex-col gap-6">
      {groups.map((group, index) => (
        <section
          className="panel relative min-w-0"
          data-rise={index + 1}
          key={group.key}
          aria-labelledby={`${group.key}-heading`}
        >
          <div className="panel-head relative flex min-h-[126px] items-center gap-5 px-[26px] pt-[50px] pb-5">
            <div className="min-w-0">
              <h2 className="panel-title absolute inset-x-[22px] top-0 m-0 flex h-[34px] items-center justify-center text-center" id={`${group.key}-heading`}>
                {group.label}
              </h2>
              <p className="panel-note m-0 max-w-[540px] text-[13px] leading-5">{group.note}</p>
            </div>
            <div aria-label={group.label} className="segmented ml-auto inline-flex gap-[5px]" role="group">
              {group.options.map(([value, label]) => (
                <PixelButton
                  aria-pressed={(config[group.key] ?? (group.key === "popup_font" ? "pixel" : "normal")) === value}
                  aria-disabled={isPending(settingPendingKey(group.key))}
                  className="segment min-w-24 h-11"
                  data-saving={isPending(settingPendingKey(group.key)) || undefined}
                  key={value}
                  onClick={() => {
                    if (isPending(settingPendingKey(group.key))) return;
                    void saveSettings({ [group.key]: value });
                  }}
                  type="button"
                >
                  {label}
                </PixelButton>
              ))}
            </div>
          </div>
        </section>
      ))}
    </div>
  );
}
