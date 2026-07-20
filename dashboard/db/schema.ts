/**
 * Drizzle schema — ingest + storage + visualization only.
 *
 * `records.data` holds the full CLI MemoryRecord verbatim (the schema is
 * additive and pinned CLI-side); hot columns are extracted at ingest for
 * querying. Advisories are extracted per-finding because E1 labels rows
 * individually and E2 groups by signature.
 */
import { sql } from "drizzle-orm";
import {
  bigint,
  boolean,
  index,
  integer,
  jsonb,
  pgTable,
  primaryKey,
  real,
  text,
  timestamp,
  uniqueIndex,
  uuid,
} from "drizzle-orm/pg-core";
import type { AdapterAccountType } from "next-auth/adapters";

// ---------------------------------------------------------------- Auth.js
// Adapter tables per @auth/drizzle-adapter, extended with GitHub identity.

export const users = pgTable("users", {
  id: uuid("id").primaryKey().defaultRandom(),
  name: text("name"),
  email: text("email").unique(),
  emailVerified: timestamp("email_verified", { withTimezone: true }),
  image: text("image"),
  githubLogin: text("github_login"),
  githubId: bigint("github_id", { mode: "number" }).unique(),
});

export const accounts = pgTable(
  "accounts",
  {
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    type: text("type").$type<AdapterAccountType>().notNull(),
    provider: text("provider").notNull(),
    providerAccountId: text("provider_account_id").notNull(),
    refresh_token: text("refresh_token"),
    access_token: text("access_token"),
    expires_at: integer("expires_at"),
    token_type: text("token_type"),
    scope: text("scope"),
    id_token: text("id_token"),
    session_state: text("session_state"),
  },
  (table) => [
    primaryKey({ columns: [table.provider, table.providerAccountId] }),
  ],
);

export const sessions = pgTable("sessions", {
  sessionToken: text("session_token").primaryKey(),
  userId: uuid("user_id")
    .notNull()
    .references(() => users.id, { onDelete: "cascade" }),
  expires: timestamp("expires", { withTimezone: true }).notNull(),
});

export const verificationTokens = pgTable(
  "verification_tokens",
  {
    identifier: text("identifier").notNull(),
    token: text("token").notNull(),
    expires: timestamp("expires", { withTimezone: true }).notNull(),
  },
  (table) => [primaryKey({ columns: [table.identifier, table.token] })],
);

// ---------------------------------------------------------------- domain

export const repos = pgTable(
  "repos",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    // The CLI repo_id ("app", "owner/repo") — unique only per user.
    repoSlug: text("repo_slug").notNull(),
    displayName: text("display_name"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (table) => [uniqueIndex("repos_user_slug").on(table.userId, table.repoSlug)],
);

export const deviceCodes = pgTable(
  "device_codes",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    deviceCodeHash: text("device_code_hash").notNull().unique(),
    userCode: text("user_code").notNull(), // "ABCD-EFGH"
    status: text("status").notNull().default("pending"), // pending|approved|denied|expired|consumed
    userId: uuid("user_id").references(() => users.id), // set on approval
    hostname: text("hostname"),
    cliVersion: text("cli_version"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    expiresAt: timestamp("expires_at", { withTimezone: true }).notNull(),
    lastPolledAt: timestamp("last_polled_at", { withTimezone: true }),
  },
  (table) => [
    // A user_code is only reserved while pending — codes can recycle.
    uniqueIndex("device_codes_active_user_code")
      .on(table.userCode)
      .where(sql`${table.status} = 'pending'`),
  ],
);

export const deviceTokens = pgTable("device_tokens", {
  id: uuid("id").primaryKey().defaultRandom(),
  userId: uuid("user_id")
    .notNull()
    .references(() => users.id, { onDelete: "cascade" }),
  tokenHash: text("token_hash").notNull().unique(), // sha256; plaintext pjt_… shown once
  name: text("name"), // hostname label from connect
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
  lastUsedAt: timestamp("last_used_at", { withTimezone: true }),
  revokedAt: timestamp("revoked_at", { withTimezone: true }),
});

export const records = pgTable(
  "records",
  {
    pk: uuid("pk").primaryKey().defaultRandom(),
    repoPk: uuid("repo_pk")
      .notNull()
      .references(() => repos.id, { onDelete: "cascade" }),
    recordId: text("record_id").notNull(), // "chk_012"
    createdAt: timestamp("created_at", { withTimezone: true }).notNull(),
    action: text("action").notNull(), // action_intercepted
    agentSource: text("agent_source").notNull(),
    gatePassed: boolean("gate_passed").notNull(),
    failureClasses: text("failure_classes").array().notNull().default([]),
    diagnosis: text("diagnosis").notNull().default(""),
    recalledFrom: text("recalled_from"), // may be "repo:chk_NNN"
    resolves: text("resolves"),
    resolutionStatus: text("resolution_status"),
    resolutionOutcome: text("resolution_outcome"),
    inputsHash: text("inputs_hash"),
    gateDurationMs: integer("gate_duration_ms").notNull().default(0),
    judgeModelId: text("judge_model_id"),
    cliVersion: text("cli_version"),
    schemaVersion: text("schema_version"),
    data: jsonb("data").notNull(), // full MemoryRecord verbatim
    ingestedAt: timestamp("ingested_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (table) => [
    uniqueIndex("records_repo_record").on(table.repoPk, table.recordId), // idempotency key
    index("records_repo_time").on(table.repoPk, table.createdAt.desc()),
    index("records_repo_verdict").on(
      table.repoPk,
      table.gatePassed,
      table.createdAt.desc(),
    ),
    index("records_classes_gin").using("gin", table.failureClasses),
  ],
);

export const advisories = pgTable(
  "advisories",
  {
    pk: uuid("pk").primaryKey().defaultRandom(),
    recordPk: uuid("record_pk")
      .notNull()
      .references(() => records.pk, { onDelete: "cascade" }),
    repoPk: uuid("repo_pk")
      .notNull()
      .references(() => repos.id, { onDelete: "cascade" }),
    recordId: text("record_id").notNull(),
    idx: integer("idx").notNull(), // ref = `${recordId}#${idx}`
    concern: text("concern").notNull(),
    kind: text("kind"), // discovery | adjudication
    tier: integer("tier"),
    confidence: real("confidence"),
    target: text("target"),
    judgeModelId: text("judge_model_id"),
    delivery: text("delivery").notNull(), // injected|held|staged|sent|suppressed
    label: text("label"), // null|confirmed|rejected
    retraction: text("retraction"), // null|staged|sent
    signature: text("signature").notNull(), // lib/signature.ts — byte-matches the CLI
    createdAt: timestamp("created_at", { withTimezone: true }).notNull(),
  },
  (table) => [
    uniqueIndex("advisories_record_idx").on(table.recordPk, table.idx),
    index("advisories_repo_sig").on(table.repoPk, table.signature),
    index("advisories_repo_label").on(table.repoPk, table.label),
  ],
);

// E1 down-sync feed: the identity column IS the CLI's pull cursor.
export const labelEvents = pgTable(
  "label_events",
  {
    id: bigint("id", { mode: "number" })
      .generatedAlwaysAsIdentity()
      .primaryKey(),
    repoPk: uuid("repo_pk")
      .notNull()
      .references(() => repos.id, { onDelete: "cascade" }),
    recordId: text("record_id").notNull(),
    kind: text("kind").notNull(), // 'advisory_label' ('resolution' reserved)
    idx: integer("idx"),
    payload: jsonb("payload").notNull(), // {label?, delivery?, retraction?}
    source: text("source").notNull().default("web"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (table) => [index("label_events_repo_seq").on(table.repoPk, table.id)],
);

export const proofFiles = pgTable(
  "proof_files",
  {
    pk: uuid("pk").primaryKey().defaultRandom(),
    recordPk: uuid("record_pk")
      .notNull()
      .references(() => records.pk, { onDelete: "cascade" }),
    name: text("name").notNull(), // checks.json|context.json|diff.patch|impact.json
    blobKey: text("blob_key").notNull(), // {userId}/{repoSlug}/{recordId}/{name}
    blobUrl: text("blob_url"), // never sent to the client — proxy route only
    sizeBytes: integer("size_bytes").notNull(),
    truncated: boolean("truncated").notNull().default(false),
  },
  (table) => [uniqueIndex("proof_files_record_name").on(table.recordPk, table.name)],
);
