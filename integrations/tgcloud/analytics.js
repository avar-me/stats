// Drop-in telemetry for a Telegram Serverless bot.
// Copy schema.snippet.js into tgcloud/schema.js, this file to tgcloud/lib/analytics.js,
// and exportAnalytics.js to tgcloud/lib/exportAnalytics.js.
//
// The module stores counters only. It has no parameter for message text, usernames
// or search queries. User ids are reduced with one HMAC key shared by the day and
// the month, so monthly uniques are not a union of rotating daily hashes.
// Retention matches the Python module: 40 days for days, 400 days for months.

import { db } from "sdk";

const EVENT = /^[A-Za-z0-9_.:-]{1,64}$/;
const DAY_RETENTION = 40;
const MONTH_RETENTION = 400;

export async function track(input) {
  try {
    await record(input || {});
  } catch (error) {
    console.warn("analytics", error && error.message ? error.message : "failed");
  }
}

export async function setSecret(secret) {
  if (!secret || String(secret).length < 16) {
    throw new Error("analytics secret must be at least 16 characters");
  }
  await db.run(
    "INSERT INTO analytics_meta (key, value) VALUES ('secret', :secret) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
    { ":secret": String(secret) },
  );
}

export async function exportAnalytics() {
  const daily = await db.all("SELECT bot, date, event, success, count, duration_sum_ms, duration_count FROM analytics_daily");
  const users = await db.all(
    "SELECT bot, period, granularity, COUNT(*) AS users FROM analytics_users GROUP BY bot, period, granularity",
  );
  const days = new Map();
  for (const row of daily) {
    const key = `${row.bot}|${row.date}`;
    if (!days.has(key)) {
      days.set(key, {
        bot: row.bot,
        date: row.date,
        requests: 0,
        successful_requests: 0,
        failed_requests: 0,
        duration_ms_sum: 0,
        duration_count: 0,
        commands: {},
      });
    }
    const bucket = days.get(key);
    const count = Number(row.count) || 0;
    bucket.requests += count;
    if (Number(row.success) === 1) bucket.successful_requests += count;
    else bucket.failed_requests += count;
    bucket.duration_ms_sum += Number(row.duration_sum_ms) || 0;
    bucket.duration_count += Number(row.duration_count) || 0;
    if (EVENT.test(String(row.event))) bucket.commands[row.event] = (bucket.commands[row.event] || 0) + count;
  }
  const months = new Map();
  for (const row of users) {
    const key = `${row.bot}|${row.period}`;
    if (row.granularity === "day") {
      const bucket = days.get(key);
      if (bucket) bucket.unique_users = Number(row.users) || 0;
    } else if (row.granularity === "month") {
      if (!months.has(row.bot)) months.set(row.bot, []);
      months.get(row.bot).push({ month: row.period, unique_users: Number(row.users) || 0 });
    }
  }
  const byBot = new Map();
  for (const bucket of days.values()) {
    if (!byBot.has(bucket.bot)) byBot.set(bucket.bot, { bot: bucket.bot, days: [], months: months.get(bucket.bot) || [] });
    const { bot, ...day } = bucket;
    byBot.get(bot).days.push(day);
  }
  return { bots: [...byBot.values()] };
}

async function record(input) {
  const bot = String(input.bot || "");
  const event = String(input.event || "");
  if (!EVENT.test(bot) || !EVENT.test(event)) return;
  const durationMs = input.durationMs == null ? null : Number(input.durationMs);
  if (durationMs != null && (!Number.isFinite(durationMs) || durationMs < 0)) return;
  const now = input.now ? new Date(input.now) : new Date();
  const day = now.toISOString().slice(0, 10);
  const month = day.slice(0, 7);
  const success = input.success ? 1 : 0;
  const duration = durationMs == null ? 0 : Math.round(durationMs);
  const durationCount = durationMs == null ? 0 : 1;
  if (input.eventId) {
    const inserted = await db.run(
      "INSERT INTO analytics_events (event_id, created_on) VALUES (:id, :day) ON CONFLICT(event_id) DO NOTHING",
      { ":id": String(input.eventId), ":day": day },
    );
    if (inserted && inserted.rowsAffected === 0) return;
  }
  await db.run(
    `INSERT INTO analytics_daily (bot, date, event, success, count, duration_sum_ms, duration_count)
     VALUES (:bot, :date, :event, :success, 1, :duration, :durationCount)
     ON CONFLICT (bot, date, event, success) DO UPDATE SET
       count = count + 1,
       duration_sum_ms = duration_sum_ms + excluded.duration_sum_ms,
       duration_count = duration_count + excluded.duration_count`,
    { ":bot": bot, ":date": day, ":event": event, ":success": success, ":duration": duration, ":durationCount": durationCount },
  );
  if (input.userId != null) {
    const secret = await readSecret();
    if (secret) {
      const digest = await hmac(secret, `${bot}:${input.userId}`);
      await db.run(
        "INSERT INTO analytics_users (bot, period, granularity, user_hash) VALUES (:bot, :period, 'day', :hash) ON CONFLICT DO NOTHING",
        { ":bot": bot, ":period": day, ":hash": digest },
      );
      await db.run(
        "INSERT INTO analytics_users (bot, period, granularity, user_hash) VALUES (:bot, :period, 'month', :hash) ON CONFLICT DO NOTHING",
        { ":bot": bot, ":period": month, ":hash": digest },
      );
    }
  }
  await purge(day);
}

async function readSecret() {
  const row = await db.get("SELECT value FROM analytics_meta WHERE key = 'secret'");
  return row && row.value ? String(row.value) : "";
}

async function hmac(secret, value) {
  const encoded = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", encoded.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = await crypto.subtle.sign("HMAC", key, encoded.encode(value));
  return [...new Uint8Array(signature)].map((byte) => byte.toString(16).padStart(2, "0")).join("").slice(0, 32);
}

async function purge(day) {
  const today = new Date(`${day}T00:00:00Z`);
  const dayCutoff = new Date(today.getTime() - DAY_RETENTION * 86400000).toISOString().slice(0, 10);
  const monthCutoff = new Date(today.getTime() - MONTH_RETENTION * 86400000).toISOString().slice(0, 7);
  await db.run("DELETE FROM analytics_users WHERE granularity = 'day' AND period < :cutoff", { ":cutoff": dayCutoff });
  await db.run("DELETE FROM analytics_users WHERE granularity = 'month' AND period < :cutoff", { ":cutoff": monthCutoff });
  await db.run("DELETE FROM analytics_events WHERE created_on < :cutoff", { ":cutoff": dayCutoff });
  await db.run("DELETE FROM analytics_daily WHERE date < :cutoff", { ":cutoff": dayCutoff });
}
