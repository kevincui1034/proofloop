/**
 * Auth.js v5. GitHub OAuth in production; a Credentials "dev login" only
 * when AUTH_DEV_LOGIN=1 outside production (local-first development).
 *
 * JWT session strategy: Credentials providers cannot create database
 * sessions, and this app needs no server-side session revocation — the
 * Drizzle adapter still persists users/accounts for GitHub sign-ins.
 */
import NextAuth, { type NextAuthConfig } from "next-auth";
import Credentials from "next-auth/providers/credentials";
import GitHub from "next-auth/providers/github";
import { DrizzleAdapter } from "@auth/drizzle-adapter";
import { eq } from "drizzle-orm";

import { db } from "@/db";
import { accounts, sessions, users, verificationTokens } from "@/db/schema";

const providers: NextAuthConfig["providers"] = [];

if (process.env.AUTH_GITHUB_ID && process.env.AUTH_GITHUB_SECRET) {
  providers.push(
    GitHub({
      clientId: process.env.AUTH_GITHUB_ID,
      clientSecret: process.env.AUTH_GITHUB_SECRET,
      profile(profile) {
        return {
          id: String(profile.id),
          name: profile.name ?? profile.login,
          email: profile.email,
          image: profile.avatar_url,
          githubLogin: profile.login,
          githubId: profile.id,
        };
      },
    }),
  );
}

const devLoginEnabled =
  process.env.AUTH_DEV_LOGIN === "1" && process.env.NODE_ENV !== "production";

if (devLoginEnabled) {
  providers.push(
    Credentials({
      id: "dev",
      name: "Dev login",
      credentials: {},
      async authorize() {
        // Upsert the fixed local user so repos/records attach to it.
        const [existing] = await db
          .select()
          .from(users)
          .where(eq(users.email, "dev@localhost"))
          .limit(1);
        if (existing) return { ...existing, id: existing.id };
        const [created] = await db
          .insert(users)
          .values({
            name: "Dev User",
            email: "dev@localhost",
            githubLogin: "dev",
          })
          .returning();
        return { ...created, id: created.id };
      },
    }),
  );
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  adapter: DrizzleAdapter(db, {
    usersTable: users,
    accountsTable: accounts,
    sessionsTable: sessions,
    verificationTokensTable: verificationTokens,
  }),
  session: { strategy: "jwt" },
  providers,
  pages: { signIn: "/login" },
  callbacks: {
    jwt({ token, user }) {
      if (user?.id) token.userId = user.id;
      return token;
    },
    session({ session, token }) {
      if (token.userId && session.user) {
        session.user.id = token.userId as string;
      }
      return session;
    },
  },
});

export { devLoginEnabled };
