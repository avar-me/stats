// Runnable export. From the bot repo, after this file lives at tgcloud/lib/exportAnalytics.js:
//   npx tgcloud run lib/exportAnalytics
// stdout is the aggregate JSON. It contains counts only.

import { exportAnalytics } from "./analytics.js";

export default async function () {
  const payload = await exportAnalytics();
  console.log(JSON.stringify(payload));
  return payload;
}
