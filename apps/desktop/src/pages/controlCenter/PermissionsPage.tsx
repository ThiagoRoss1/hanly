import { useEffect } from "react";
import type { HanlyState, PermissionItem } from "../../contracts/desktop.ts";
import { PixelButton } from "../../components/PixelButton.tsx";
import type { IsPending, RunCommand } from "./types.ts";

export function PermissionsPage({
  state,
  isPending,
  run,
}: {
  state: HanlyState;
  isPending: IsPending;
  run: RunCommand;
}) {
  const permissions = state.permissions;
  const items = permissions.items ?? [];
  const missing = items.filter((item) => !item.granted);
  useEffect(() => {
    if (!permissions.supported) return;
    const refresh = () => void run("refresh_permissions");
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [permissions.supported, run]);

  return (
    <div className="page flex max-w-none flex-col gap-6">
      <section className="panel panel-quiet relative min-w-0" data-rise="1">
        <div className="panel-head relative flex min-h-[104px] items-center gap-5 px-[26px] pt-[50px] pb-5">
          <div className="min-w-0">
            <h2 className="panel-title absolute inset-x-[22px] top-0 m-0 flex h-[34px] items-center justify-center text-center">Desktop access</h2>
            <p className="panel-note m-0 max-w-[540px] text-[13px] leading-5">
              Permission grants are checked by Hanly before capture begins.
            </p>
          </div>
          <PixelButton
            className="btn btn-sm ml-auto"
            disabled={isPending("refresh_permissions") || !permissions.supported}
            onClick={() => void run("refresh_permissions")}
            type="button"
          >
            Recheck
          </PixelButton>
        </div>
        {!permissions.supported ? (
          <div className="panel-rows flex flex-col px-4 pb-4">
            <div className="readiness-row flex min-h-11 flex-wrap items-center gap-3 py-3">
              <span className="readiness-detail min-w-[110px] flex-1 text-[13px] leading-5">
                {permissions.available === false
                  ? permissions.message ||
                    "Permission checks are not connected in this build."
                  : "This platform does not require a separate permission check."}
              </span>
            </div>
          </div>
        ) : (
          <>
            {missing.length > 0 && (
              <div
                aria-live="polite"
                className="permission-onboarding relative mx-4 mb-3 flex flex-col gap-[3px] border border-[#d5b66e] px-5 pt-[14px] pb-[14px] pl-[62px]"
                role="status"
              >
                <strong>Before Hanly can read</strong>
                <span>
                  Grant the required desktop access, then return here and
                  recheck.
                </span>
                <span>
                  Grant access opens System Settings: switch Hanly on there.
                  An entry already switched on belongs to an earlier copy of
                  Hanly; Grant access clears it, so switch the new one on.
                </span>
              </div>
            )}
            <div className="panel-rows flex flex-col gap-3 px-4 pb-4">
              {items.map((item) => (
                <PermissionCard
                  key={item.id}
                  item={item}
                  busy={isPending("grant_permission")}
                  onGrant={() =>
                    void run("grant_permission", { permission: item.id })
                  }
                />
              ))}
            </div>
          </>
        )}
        <p className="panel-note m-0 px-4 pb-4 text-[13px] leading-5">
          Granted permissions stay listed so you can see what Hanly is using.
        </p>
      </section>
    </div>
  );
}

export function PermissionCard({
  item,
  busy,
  onGrant,
}: {
  item: PermissionItem;
  busy: boolean;
  onGrant: () => void;
}) {
  const tone = item.granted ? "ok" : item.state === "unknown" ? "warn" : "bad";
  return (
    <div className="permission flex items-center gap-3 border border-[var(--skin-line)] px-4 py-5" data-granted={item.granted}>
      <span
        aria-hidden="true"
        className="dot h-2 w-2 shrink-0"
        data-tone={item.granted ? "ok" : "info"}
      />
      <div className="min-w-0 flex-1">
        <div className="permission-head flex flex-wrap items-center gap-2">
          <span className="permission-name text-sm leading-5">{item.label}</span>
          <span className="tag" data-tone={tone}>
            {item.granted
              ? "granted"
              : item.state === "unknown"
                ? "unknown"
                : "required"}
          </span>
        </div>
        <div className="permission-why mt-0.5 max-w-[470px] text-[13px] leading-5">
          {item.requirement} {item.granted ? "" : item.restart_note}
        </div>
      </div>
      {!item.granted && (
        <PixelButton
          className="btn btn-sm btn-primary"
          data-art-role="mint"
          disabled={busy}
          onClick={onGrant}
          type="button"
        >
          Grant access
        </PixelButton>
      )}
    </div>
  );
}
