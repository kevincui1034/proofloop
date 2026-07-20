"use client";

import { useActionState } from "react";

import type { ActionState } from "@/app/(dashboard)/repos/[repoId]/traces/[recordId]/actions";
import { labelAction } from "@/app/(dashboard)/repos/[repoId]/traces/[recordId]/actions";

const INITIAL: ActionState = { error: null };

export function AdvisoryActions({
  advisoryPk,
  delivery,
  label,
  path,
}: {
  advisoryPk: string;
  delivery: string;
  label: string | null;
  path: string;
}) {
  const [state, dispatch, pending] = useActionState(labelAction, INITIAL);
  const canApprove = delivery === "held" && !label;
  const decided = label !== null;

  return (
    <form action={dispatch} className="flex flex-wrap items-center gap-2">
      <input type="hidden" name="advisoryPk" value={advisoryPk} />
      <input type="hidden" name="path" value={path} />
      {canApprove && (
        <button
          type="submit"
          name="action"
          value="approve"
          disabled={pending}
          className="rounded-md border border-amber/60 px-3 py-1 text-xs text-amber-ink hover:bg-amber/10 disabled:opacity-50"
        >
          Approve → agent
        </button>
      )}
      {!decided && (
        <>
          <button
            type="submit"
            name="action"
            value="confirm"
            disabled={pending}
            className="rounded-md border border-verdict-green/50 px-3 py-1 text-xs text-verdict-green hover:bg-verdict-green/10 disabled:opacity-50"
          >
            Confirm correct
          </button>
          <button
            type="submit"
            name="action"
            value="reject"
            disabled={pending}
            className="rounded-md border border-verdict-red/50 px-3 py-1 text-xs text-verdict-red hover:bg-verdict-red/10 disabled:opacity-50"
          >
            Reject
          </button>
        </>
      )}
      {decided && (
        <span className="text-xs text-faint">
          labeled — syncs to the CLI on its next pull
        </span>
      )}
      {state.error && (
        <span className="text-xs text-verdict-red">{state.error}</span>
      )}
      <span className="ml-auto text-xs text-faint">
        reaches your agent on its next gate run after sync
      </span>
    </form>
  );
}
