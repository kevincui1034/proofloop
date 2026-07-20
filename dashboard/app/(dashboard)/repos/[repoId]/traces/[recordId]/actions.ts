"use server";

import { revalidatePath } from "next/cache";

import { auth } from "@/auth";
import {
  approveAdvisory,
  confirmAdvisory,
  LabelError,
  rejectAdvisory,
} from "@/lib/labels";

export interface ActionState {
  error: string | null;
}

async function run(
  action: "approve" | "reject" | "confirm",
  advisoryPk: string,
  path: string,
): Promise<ActionState> {
  const session = await auth();
  if (!session?.user?.id) return { error: "not signed in" };
  const ref = { advisoryPk, userId: session.user.id };
  try {
    if (action === "approve") await approveAdvisory(ref);
    else if (action === "reject") await rejectAdvisory(ref);
    else await confirmAdvisory(ref);
  } catch (error) {
    if (error instanceof LabelError) return { error: error.message };
    throw error;
  }
  revalidatePath(path);
  return { error: null };
}

export async function labelAction(
  _prev: ActionState,
  formData: FormData,
): Promise<ActionState> {
  return run(
    formData.get("action") as "approve" | "reject" | "confirm",
    String(formData.get("advisoryPk")),
    String(formData.get("path")),
  );
}
