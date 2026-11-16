// Add these exports to the bot's tgcloud/schema.js. Do not replace the whole file.
// Tables hold counters and HMAC digests. They do not hold user ids or message text.

import { index, integer, primaryKey, table, text } from "sdk/db";

export const analyticsDaily = table("analytics_daily", {
  bot: text("bot").notNull(),
  date: text("date").notNull(),
  event: text("event").notNull(),
  success: integer("success").notNull(),
  count: integer("count").notNull().default(0),
  durationSum: integer("duration_sum_ms").notNull().default(0),
  durationCount: integer("duration_count").notNull().default(0),
}, (t) => ({
  pk: primaryKey({ columns: [t.bot, t.date, t.event, t.success] }),
}));

export const analyticsUsers = table("analytics_users", {
  bot: text("bot").notNull(),
  period: text("period").notNull(),
  granularity: text("granularity").notNull(),
  userHash: text("user_hash").notNull(),
}, (t) => ({
  pk: primaryKey({ columns: [t.bot, t.period, t.granularity, t.userHash] }),
  periodIdx: index("idx_analytics_users_period").on(t.granularity, t.period),
}));

export const analyticsEvents = table("analytics_events", {
  eventId: text("event_id").primaryKey(),
  createdOn: text("created_on").notNull(),
});

export const analyticsMeta = table("analytics_meta", {
  key: text("key").primaryKey(),
  value: text("value").notNull(),
});
