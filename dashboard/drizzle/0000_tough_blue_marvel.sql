CREATE TABLE "accounts" (
	"user_id" uuid NOT NULL,
	"type" text NOT NULL,
	"provider" text NOT NULL,
	"provider_account_id" text NOT NULL,
	"refresh_token" text,
	"access_token" text,
	"expires_at" integer,
	"token_type" text,
	"scope" text,
	"id_token" text,
	"session_state" text,
	CONSTRAINT "accounts_provider_provider_account_id_pk" PRIMARY KEY("provider","provider_account_id")
);
--> statement-breakpoint
CREATE TABLE "advisories" (
	"pk" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"record_pk" uuid NOT NULL,
	"repo_pk" uuid NOT NULL,
	"record_id" text NOT NULL,
	"idx" integer NOT NULL,
	"concern" text NOT NULL,
	"kind" text,
	"tier" integer,
	"confidence" real,
	"target" text,
	"judge_model_id" text,
	"delivery" text NOT NULL,
	"label" text,
	"retraction" text,
	"signature" text NOT NULL,
	"created_at" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE TABLE "device_codes" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"device_code_hash" text NOT NULL,
	"user_code" text NOT NULL,
	"status" text DEFAULT 'pending' NOT NULL,
	"user_id" uuid,
	"hostname" text,
	"cli_version" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"expires_at" timestamp with time zone NOT NULL,
	"last_polled_at" timestamp with time zone,
	CONSTRAINT "device_codes_device_code_hash_unique" UNIQUE("device_code_hash")
);
--> statement-breakpoint
CREATE TABLE "device_tokens" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"token_hash" text NOT NULL,
	"name" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"last_used_at" timestamp with time zone,
	"revoked_at" timestamp with time zone,
	CONSTRAINT "device_tokens_token_hash_unique" UNIQUE("token_hash")
);
--> statement-breakpoint
CREATE TABLE "label_events" (
	"id" bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY (sequence name "label_events_id_seq" INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START WITH 1 CACHE 1),
	"repo_pk" uuid NOT NULL,
	"record_id" text NOT NULL,
	"kind" text NOT NULL,
	"idx" integer,
	"payload" jsonb NOT NULL,
	"source" text DEFAULT 'web' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "proof_files" (
	"pk" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"record_pk" uuid NOT NULL,
	"name" text NOT NULL,
	"blob_key" text NOT NULL,
	"blob_url" text,
	"size_bytes" integer NOT NULL,
	"truncated" boolean DEFAULT false NOT NULL
);
--> statement-breakpoint
CREATE TABLE "records" (
	"pk" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"repo_pk" uuid NOT NULL,
	"record_id" text NOT NULL,
	"created_at" timestamp with time zone NOT NULL,
	"action" text NOT NULL,
	"agent_source" text NOT NULL,
	"gate_passed" boolean NOT NULL,
	"failure_classes" text[] DEFAULT '{}' NOT NULL,
	"diagnosis" text DEFAULT '' NOT NULL,
	"recalled_from" text,
	"resolves" text,
	"resolution_status" text,
	"resolution_outcome" text,
	"inputs_hash" text,
	"gate_duration_ms" integer DEFAULT 0 NOT NULL,
	"judge_model_id" text,
	"cli_version" text,
	"schema_version" text,
	"data" jsonb NOT NULL,
	"ingested_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "repos" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"repo_slug" text NOT NULL,
	"display_name" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "sessions" (
	"session_token" text PRIMARY KEY NOT NULL,
	"user_id" uuid NOT NULL,
	"expires" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE TABLE "users" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"name" text,
	"email" text,
	"email_verified" timestamp with time zone,
	"image" text,
	"github_login" text,
	"github_id" bigint,
	CONSTRAINT "users_email_unique" UNIQUE("email"),
	CONSTRAINT "users_github_id_unique" UNIQUE("github_id")
);
--> statement-breakpoint
CREATE TABLE "verification_tokens" (
	"identifier" text NOT NULL,
	"token" text NOT NULL,
	"expires" timestamp with time zone NOT NULL,
	CONSTRAINT "verification_tokens_identifier_token_pk" PRIMARY KEY("identifier","token")
);
--> statement-breakpoint
ALTER TABLE "accounts" ADD CONSTRAINT "accounts_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "advisories" ADD CONSTRAINT "advisories_record_pk_records_pk_fk" FOREIGN KEY ("record_pk") REFERENCES "public"."records"("pk") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "advisories" ADD CONSTRAINT "advisories_repo_pk_repos_id_fk" FOREIGN KEY ("repo_pk") REFERENCES "public"."repos"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "device_codes" ADD CONSTRAINT "device_codes_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "device_tokens" ADD CONSTRAINT "device_tokens_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "label_events" ADD CONSTRAINT "label_events_repo_pk_repos_id_fk" FOREIGN KEY ("repo_pk") REFERENCES "public"."repos"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "proof_files" ADD CONSTRAINT "proof_files_record_pk_records_pk_fk" FOREIGN KEY ("record_pk") REFERENCES "public"."records"("pk") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "records" ADD CONSTRAINT "records_repo_pk_repos_id_fk" FOREIGN KEY ("repo_pk") REFERENCES "public"."repos"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "repos" ADD CONSTRAINT "repos_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "sessions" ADD CONSTRAINT "sessions_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "advisories_record_idx" ON "advisories" USING btree ("record_pk","idx");--> statement-breakpoint
CREATE INDEX "advisories_repo_sig" ON "advisories" USING btree ("repo_pk","signature");--> statement-breakpoint
CREATE INDEX "advisories_repo_label" ON "advisories" USING btree ("repo_pk","label");--> statement-breakpoint
CREATE UNIQUE INDEX "device_codes_active_user_code" ON "device_codes" USING btree ("user_code") WHERE "device_codes"."status" = 'pending';--> statement-breakpoint
CREATE INDEX "label_events_repo_seq" ON "label_events" USING btree ("repo_pk","id");--> statement-breakpoint
CREATE UNIQUE INDEX "proof_files_record_name" ON "proof_files" USING btree ("record_pk","name");--> statement-breakpoint
CREATE UNIQUE INDEX "records_repo_record" ON "records" USING btree ("repo_pk","record_id");--> statement-breakpoint
CREATE INDEX "records_repo_time" ON "records" USING btree ("repo_pk","created_at" DESC NULLS LAST);--> statement-breakpoint
CREATE INDEX "records_repo_verdict" ON "records" USING btree ("repo_pk","gate_passed","created_at" DESC NULLS LAST);--> statement-breakpoint
CREATE INDEX "records_classes_gin" ON "records" USING gin ("failure_classes");--> statement-breakpoint
CREATE UNIQUE INDEX "repos_user_slug" ON "repos" USING btree ("user_id","repo_slug");