import { useState } from "react";
import type { HanlyState, RuntimeResource } from "../../contracts/desktop.ts";
import { PixelButton } from "../../components/PixelButton.tsx";
import { PixelProgress } from "../../components/PixelProgress.tsx";
import {
  UPDATE_BUSY,
  describePlan,
  formatBytes,
  titleCase,
  valueText,
} from "./helpers.ts";
import type { IsPending, RunCommand } from "./types.ts";

export function UpdatesPage({
  state,
  isPending,
  run,
}: {
  state: HanlyState;
  isPending: IsPending;
  run: RunCommand;
}) {
  const updates = state.updates;
  const [resourcesOpen, setResourcesOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  const application = updates.application;
  const isBusy = UPDATE_BUSY.has(updates.status ?? "");
  const availableResources = new Map(
    (updates.resources ?? [])
      .filter((resource) => resource.available)
      .map((item) => [item.id, item]),
  );
  const resources = state.runtime.resources;
  const activity = updates.activity ?? [];
  const progress = updates.progress;
  const fraction =
    typeof progress?.fraction === "number"
      ? Math.max(0, Math.min(1, progress.fraction))
      : progress?.total
        ? Math.max(0, Math.min(1, (progress.completed ?? 0) / progress.total))
        : null;
  const bytesLine = progress?.total
    ? `${formatBytes(progress.completed ?? 0)} / ${formatBytes(progress.total)}`
    : "";

  return (
    <div className="page flex max-w-none flex-col gap-6">
      <section
        className="panel relative min-w-0"
        data-tone={
          updates.status === "failed"
            ? "bad"
            : application?.installable || updates.awaiting_confirmation
              ? "accent"
              : undefined
        }
        data-rise="1"
      >
        <div className="panel-head relative flex min-h-[104px] items-center gap-5 px-[26px] pt-[50px] pb-5">
          <div className="min-w-0">
            <h2 className="panel-title absolute inset-x-[22px] top-0 m-0 flex h-[34px] items-center justify-center text-center">Hanly application</h2>
            <p className="panel-note m-0 max-w-[540px] text-[13px] leading-5">
              Application files update separately from dictionary resources.
            </p>
          </div>
          <span
            className="tag ml-auto px-[9px] py-[3px]"
            data-tone={
              updates.status === "failed"
                ? "bad"
                : application?.installable
                  ? "accent"
                  : "ok"
            }
          >
            {valueText(updates.status, "not checked")}
          </span>
        </div>
        {isBusy ? (
          <div className="update-busy grid min-h-[170px] grid-cols-1 grid-rows-[auto_30px_auto] gap-3.5 px-[26px] pt-[22px] pb-[26px]">
            <div className="update-busy-line grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3">
              <span className="update-strong min-w-0 text-sm leading-[22px] font-bold">
                {updates.message || titleCase(updates.status)}
              </span>
              <span className="update-detail whitespace-nowrap font-mono text-[11px]">{bytesLine}</span>
              <span className="update-percent min-w-10 text-right font-mono text-xs">
                {fraction === null ? "" : `${Math.round(fraction * 100)}%`}
              </span>
            </div>
            <PixelProgress fraction={fraction} />
            {updates.cancellable && (
              <div className="update-actions flex flex-wrap gap-3">
                <PixelButton
                  className="btn btn-sm btn-quiet"
                  disabled={isPending("cancel_update")}
                  onClick={() => void run("cancel_update")}
                  type="button"
                >
                  Cancel
                </PixelButton>
              </div>
            )}
          </div>
        ) : updates.restart_required || updates.status === "restart" ? (
          <div className="update-line flex min-h-28 flex-wrap items-center gap-3 px-[26px] py-6">
            <div>
              <div className="update-strong">Ready to restart</div>
              <div className="update-sub">
                {updates.message ||
                  "Hanly restarts into the new build. Your settings stay."}
              </div>
            </div>
          </div>
        ) : updates.awaiting_confirmation ? (
          <div className="update-block update-confirmation relative flex flex-col gap-2.5 px-[26px] py-6">
            <div className="update-strong text-base leading-6 font-bold">
              This installation needs the full download
            </div>
            <div className="update-sub">{updates.message}</div>
            <div className="update-actions flex flex-wrap gap-3">
              <PixelButton
                className="btn btn-primary"
                disabled={isPending("install_application_update")}
                onClick={() =>
                  void run("install_application_update", { confirm_full: true })
                }
                type="button"
              >
                Download full update
              </PixelButton>
              <PixelButton
                className="btn btn-quiet"
                disabled={isPending("cancel_update")}
                onClick={() => void run("cancel_update")}
                type="button"
              >
                Not now
              </PixelButton>
            </div>
          </div>
        ) : application?.installable ? (
          <div className="update-block flex flex-col gap-2.5 px-[26px] py-6">
            <div className="update-versions flex flex-wrap items-baseline gap-2">
                <span className="update-from font-mono text-[13px]">
                {application.current_version ?? "Current"}
              </span>
              <span className="update-from font-mono text-[13px]">→</span>
              <span className="update-to font-mono text-[19px] font-bold">{application.latest_version}</span>
              {updates.plan && (
                <span className="update-size text-xs">
                  · {describePlan(updates.plan)}
                </span>
              )}
            </div>
            {application.message && (
              <p className="update-sub mt-0 text-[13px] leading-5">{application.message}</p>
            )}
            <div className="update-actions flex flex-wrap gap-3">
              <PixelButton
                className="btn btn-primary"
                disabled={isPending("install_application_update")}
                onClick={() =>
                  void run("install_application_update", {
                    confirm_full: false,
                  })
                }
                type="button"
              >
                Install update
              </PixelButton>
              {application.release_url && (
                <PixelButton
                  className="btn btn-quiet"
                  disabled={isPending("open_release_notes")}
                  onClick={() => void run("open_release_notes")}
                  type="button"
                >
                  View release notes
                </PixelButton>
              )}
            </div>
          </div>
        ) : updates.status === "failed" ? (
          <div className="update-line flex min-h-28 flex-wrap items-center gap-3 px-[26px] py-6">
            <div>
              <div className="update-strong text-base leading-6 font-bold">Update check failed</div>
              <div className="update-sub mt-0 text-[13px] leading-5" role="alert">
                {updates.message ||
                  application?.message ||
                  "Hanly could not check for updates."}
              </div>
            </div>
            <PixelButton
              className="btn"
              disabled={isPending("check_for_updates")}
              onClick={() => void run("check_for_updates")}
              type="button"
            >
              Try again
            </PixelButton>
          </div>
        ) : (
          <div className="update-line flex min-h-28 flex-wrap items-center gap-3 px-[26px] py-6">
            <div>
              <div className="update-strong text-base leading-6 font-bold">
                Hanly {state.runtime.app_version ?? ""}
              </div>
              <div className="update-sub mt-0 text-[13px] leading-5">
                {updates.message ||
                  application?.message ||
                  "No update check has been run."}
              </div>
            </div>
            <PixelButton
              className="btn"
              disabled={isPending("check_for_updates")}
              onClick={() => void run("check_for_updates")}
              type="button"
            >
              Check now
            </PixelButton>
          </div>
        )}
      </section>

      <section className="panel relative min-w-0" data-rise="2">
        <PixelButton
          aria-controls="resource-collapse"
          aria-expanded={resourcesOpen}
          className="disclosure relative z-0 grid min-h-[66px] w-full grid-cols-[20px_minmax(0,1fr)_24px] items-center gap-3 px-[26px] py-5 text-center"
          onClick={() => setResourcesOpen((open) => !open)}
          type="button"
        >
          <span aria-hidden="true" className="disclosure-caret justify-self-start text-xs leading-[18px]">
            ▾
          </span>
          Dictionary and resources
          <span className="disclosure-summary justify-self-end text-[11px] leading-[17px]">{resources.length}</span>
        </PixelButton>
        <div
          aria-hidden={!resourcesOpen}
          inert={!resourcesOpen}
          className="region-collapse grid grid-rows-[0fr] transition-[grid-template-rows] duration-[250ms] ease-out"
          data-open={resourcesOpen}
          id="resource-collapse"
        >
          <div className="collapse-inner">
            <div className="panel-rows flex flex-col px-4 pb-4">
              {resources.length === 0 ? (
                <p className="resource-foot m-0 px-0 py-[10px] text-xs leading-[19px] text-[var(--skin-ink-muted)]">
                  No local resources have been reported yet.
                </p>
              ) : (
                resources.map((resource) => (
                  <ResourceRow
                    key={resource.id}
                    resource={resource}
                    offered={availableResources.get(resource.id)}
                    busy={isBusy || isPending(`install_update:${resource.id}`)}
                    install={() =>
                      void run(
                        "install_update",
                        { resource_id: resource.id },
                        `install_update:${resource.id}`,
                      )
                    }
                  />
                ))
              )}
            </div>
            <p className="resource-foot m-0 px-0 py-3 text-[12px] leading-[19px]">
              Resources swap without restarting. Lookups pause for a moment
              during the swap.
            </p>
          </div>
        </div>
      </section>
      <section className="panel panel-quiet relative min-w-0" data-rise="3">
        <PixelButton
          aria-controls="activity-collapse"
          aria-expanded={activityOpen}
          className="disclosure relative z-0 grid min-h-[66px] w-full grid-cols-[20px_minmax(0,1fr)_24px] items-center gap-3 px-[26px] py-5 text-center"
          onClick={() => setActivityOpen((open) => !open)}
          type="button"
        >
          <span aria-hidden="true" className="disclosure-caret justify-self-start text-xs leading-[18px]">
            ▾
          </span>
          Update activity
          <span className="disclosure-summary justify-self-end text-[11px] leading-[17px]">{activity.length}</span>
        </PixelButton>
        <div
          aria-hidden={!activityOpen}
          inert={!activityOpen}
          className="region-collapse grid grid-rows-[0fr] transition-[grid-template-rows] duration-[250ms] ease-out"
          data-open={activityOpen}
          id="activity-collapse"
        >
          <div className="collapse-inner">
            <div
              className="panel-rows flex flex-col border-t border-[var(--skin-line)] px-4 pb-4"
              style={{ borderTop: "1px solid var(--border)" }}
            >
              {activity.length ? (
                activity.map((item, index) => (
                  <div className="log-row flex flex-wrap items-baseline gap-x-3 gap-y-2 py-3 font-mono text-[11.5px] leading-[18px]" key={`${item.at ?? index}-${index}`}>
                    <span className="log-time shrink-0 text-[var(--skin-ink-muted)]">
                      {item.at
                        ? new Date(item.at * 1000).toLocaleTimeString()
                        : ""}
                    </span>
                    <span className="log-message min-w-0 flex-1 font-sans text-[13px] leading-5 [overflow-wrap:anywhere]">{item.message}</span>
                  </div>
                ))
              ) : (
                <p className="resource-foot m-0 px-0 py-3 text-[12px] leading-[19px]">
                  No update activity has been reported.
                </p>
              )}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

export function ResourceRow({
  resource,
  offered,
  busy,
  install,
}: {
  resource: RuntimeResource;
  offered?: { id: string; available?: boolean; version?: string };
  busy: boolean;
  install: () => void;
}) {
  return (
    <div className="resource-row flex flex-wrap items-center gap-2.5 border-b border-[var(--skin-line)] py-[11px]">
      <div className="resource-text min-w-[150px] flex-1">
        <div className="resource-name font-mono font-bold text-xs leading-[18px] text-[var(--skin-ink)]">{resource.id}</div>
        <div className="resource-detail mt-px text-[13px] leading-5 text-[var(--skin-ink-muted)]">
          {[
            resource.kind,
            resource.version ? `v${resource.version}` : "version not reported",
            resource.compatible ? "compatible" : "review needed",
            offered?.version ? `→ v${offered.version}` : "",
          ]
            .filter(Boolean)
            .join(" · ")}
        </div>
      </div>
      <span
        className="tag"
        data-tone={
          offered?.available ? "accent" : resource.compatible ? "ok" : "warn"
        }
      >
        {offered?.available ? "update available" : valueText(resource.status)}
      </span>
      {offered?.available && (
        <PixelButton
          className="btn btn-sm"
          disabled={busy}
          onClick={install}
          type="button"
        >
          Install
        </PixelButton>
      )}
    </div>
  );
}
