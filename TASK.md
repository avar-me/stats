
# TASK: stats.avar.me — Public Analytics Dashboard

## 1. Project Overview

Create a public analytics dashboard for the avar.me ecosystem.

Domain: https://stats.avar.me

The dashboard should aggregate and visualize usage statistics from multiple independent services:

1. iOS application (App Store)
2. Android application (Google Play)
3. Telegram channels
4. Telegram bots (hosted on Telegram Serverless)
5. Telegram sticker packs
6. Websites and web services (Cloudflare)

The goal is to provide transparent, publicly accessible statistics about the growth and usage of the avar.me ecosystem.

The dashboard must update automatically, require minimal maintenance, and be inexpensive to operate.

## 2. Technology Stack

Preferred technologies:

- Python 3.12+ for data collection
- GitHub Actions for scheduled jobs
- Static frontend: HTML, CSS, JavaScript
- Chart.js or equivalent for charts
- JSON for publishing aggregated data
- GitHub Pages or Cloudflare Pages for hosting

Avoid unnecessary frameworks, databases, servers, and infrastructure.

If persistent storage is required, prefer a lightweight solution such as SQLite, Cloudflare R2, or versioned JSON files.

The public website must work without a backend server.

## 3. Dashboard Requirements

### 3.1 Overview Page

Display summary cards for:

- iOS downloads
- Android installs
- Telegram channel subscribers
- Telegram bot usage
- Telegram sticker packs
- Website visitors

Each card should show:

- Current metric value
- Change over the last 7 days
- Change over the last 30 days
- Last successful update

Show historical charts where data is available.

Support time ranges:

- 7 days
- 30 days
- 90 days
- 1 year
- All time

Never invent missing historical values.

### 3.2 Visual Design

Create a modern, minimalistic dashboard consistent with the avar.me ecosystem.

Requirements:

- Responsive layout
- Mobile-first design
- Light and dark themes
- Fast loading
- Accessible charts and labels
- Russian interface initially
- Architecture supporting future localization

Use a clean design without excessive animation.

### 3.3 Metric Definitions

Every metric must have a clear definition.

For example:

- Downloads: first-time downloads or total downloads
- Installs: device installations or user acquisitions
- Visitors: unique visitors within a specified period
- Subscribers: current channel membership count
- Bot users: distinct users interacting with the bot during a period

Different metrics must not be incorrectly combined.

In particular, do not sum downloads, subscribers, and visitors into a single "unique users" number.

## 4. iOS Application Statistics

Application:

https://ios.avar.me

App Store ID: 6782280983

### Data Source

Apple App Store Connect API.

Investigate the official Analytics Reports API and available download reports.

### Metrics

Collect, where available:

- First-time downloads
- Total downloads
- Downloads per day
- Downloads by country
- Downloads by device
- Historical cumulative downloads

### Implementation

Create a Python collector:

`collectors/apple.py`

Requirements:

- Authenticate using App Store Connect API credentials.
- Download available analytics reports.
- Parse and normalize reports.
- Handle delayed report availability.
- Avoid duplicate records.
- Preserve historical data.
- Support initial historical backfill.

Required secrets may include:

- APPLE_KEY_ID
- APPLE_ISSUER_ID
- APPLE_PRIVATE_KEY
- APPLE_APP_ID

Verify actual API permissions and report availability.

Do not assume every metric is accessible through the API.

## 5. Android Application Statistics

Application package:

`me.avar.dictionary`

### Data Source

Google Play Console reporting exports and supported Google APIs.

Investigate whether required statistics can be retrieved through official APIs or scheduled exports.

### Metrics

Collect, where available:

- First-time installers
- Current installed audience
- Installations per day
- Uninstallations
- Country distribution
- Historical trends

### Implementation

Create:

`collectors/google_play.py`

Requirements:

- Use official supported reporting mechanisms.
- Support scheduled report downloads.
- Normalize reports into the common data model.
- Avoid double-counting.
- Handle delayed reports.

If an API does not provide a particular metric, document the limitation and offer a supported export-based workflow.

Do not use scraping as the primary implementation.

## 6. Telegram Channel Statistics

Support one or more Telegram channels.

Channels must be configurable.

Example configuration:

```yaml
telegram_channels:
  - username: calculate_me
    enabled: true
```

### 6.1 Basic Metrics

Use Telegram Bot API where possible.

Collect:

- Current subscriber count
- Daily subscriber snapshots
- Subscriber growth
- Historical growth based on collected snapshots

The bot must have appropriate access to the channel.

Relevant API:

`getChatMemberCount`

### 6.2 Advanced Metrics

Investigate MTProto and Telethon.

Potential metrics:

- Post views
- Reactions
- Forwards
- Post engagement
- Channel statistics

Advanced statistics should only be implemented when supported by Telegram and the account has appropriate permissions.

Use Bot API for basic metrics and MTProto only when necessary.

Create:

`collectors/telegram_channels.py`

## 7. Telegram Bot Statistics

Telegram bots are hosted on Telegram Serverless.

The architecture must account for the serverless execution environment.

Example bot:

`@avar_me_bot`

Additional bots should be configurable.

### 7.1 Required Metrics

Collect, where technically possible:

- Total requests
- Requests per day
- Unique users per day
- Unique users per month
- Successful requests
- Failed requests
- Error rate
- Average processing time
- Usage by bot

Optional metrics:

- Most frequently used commands
- Request categories
- Response latency percentiles
- Active users over time

### 7.2 Important Limitation

Telegram Bot API does not provide historical bot usage analytics automatically.

These metrics must be collected by instrumenting bot handlers or by processing existing reliable logs.

Investigate what Telegram Serverless exposes:

- Execution logs
- Request counters
- Invocation metrics
- Error metrics
- Persistent storage
- Available monitoring APIs

Do not assume that the hosting platform exposes all required statistics.

### 7.3 Instrumentation

Implement a reusable Python analytics module for bot handlers.

Example:

```python
track_event(
    bot="avar_me_bot",
    event="dictionary_lookup",
    success=True,
    duration_ms=120
)
```

The module should:

- Have minimal overhead
- Avoid blocking normal bot responses
- Handle telemetry failures gracefully
- Work in a serverless environment
- Avoid duplicate events
- Minimize storage and network requests

### 7.4 Privacy

Do not publish:

- Telegram user IDs
- Usernames
- Message contents
- Search queries
- IP addresses
- Individual user activity

Publish aggregated statistics only.

If unique-user metrics require identifiers, use privacy-preserving deduplication with an explicitly documented retention policy.

Do not use a rotating daily hash to calculate monthly unique users without accounting for cross-day deduplication.

### 7.5 Data Storage

Choose a storage mechanism compatible with Telegram Serverless.

Possible options:

- Existing persistent storage
- External aggregation endpoint
- Cloudflare Workers
- Cloudflare D1
- Cloudflare R2

Prefer collecting aggregated events or counters rather than storing raw messages.

Create:

`collectors/telegram_bots.py`

And, if needed:

`integrations/telegram_bot_analytics.py`

## 8. Telegram Sticker Pack Statistics

Support one or more Telegram sticker packs.

Sticker packs should be configurable.

Example:

```yaml
telegram_stickers:
  - name: example_avar_stickers
    enabled: true
```

Replace the placeholder with the actual sticker pack name.

### 8.1 Available Metadata

Investigate Telegram Bot API:

`getStickerSet`

Collect:

- Sticker pack name
- Sticker pack title
- Number of stickers
- Sticker types
- Emoji associations, where available
- Public sticker pack link
- Last metadata update

### 8.2 Historical Statistics

Store daily snapshots of:

- Sticker count
- Sticker pack metadata
- Changes in pack composition

### 8.3 Installation and Usage Statistics

Investigate whether Telegram provides an official, reliable mechanism for retrieving:

- Sticker pack installations
- Sticker usage count
- Number of users

Important:

Telegram Bot API does not generally expose installation or usage counts for arbitrary sticker packs.

Do not invent these metrics.

If unavailable, display:

"Статистика установок недоступна через Telegram API"

Do not present sticker count as installation count.

### 8.4 Optional Alternative

If reliable usage statistics are unavailable, display a sticker pack information card containing:

- Sticker pack title
- Number of stickers
- Preview
- Link to install the pack

Create:

`collectors/telegram_stickers.py`

## 9. Website Statistics — Cloudflare

Collect analytics for websites in the avar.me ecosystem.

Initial candidate services:

- avar.me
- ios.avar.me
- en.avar.me
- forms.avar.me
- corrector.avar.me
- sources.avar.me
- dev.avar.me
- index.avar.me
- stats.avar.me

The actual list must be configurable.

### 9.1 Data Sources

Investigate:

- Cloudflare Web Analytics
- Cloudflare GraphQL Analytics API
- Cloudflare Zone Analytics

Important distinction:

Cloudflare Zone Analytics measures HTTP traffic, including automated requests.

Cloudflare Web Analytics is more appropriate for human-facing page analytics.

Do not treat HTTP requests as unique visitors.

### 9.2 Metrics

Collect, where available:

- Page views
- Visits
- Unique visitors
- Visitors by country
- Traffic over time
- Top pages
- Referrers
- HTTP requests, separately from visits

### 9.3 Multi-Site Support

The dashboard should support multiple websites.

Example:

```yaml
websites:
  - hostname: avar.me
    provider: cloudflare_web_analytics
    enabled: true

  - hostname: en.avar.me
    provider: cloudflare_web_analytics
    enabled: true
```

Support websites hosted on GitHub Pages, Cloudflare Pages, and other platforms.

Verify that analytics collection is configured correctly for each site.

If Cloudflare Web Analytics requires a JavaScript beacon, document and implement the required integration.

### 9.4 API Implementation

Create:

`collectors/cloudflare.py`

Requirements:

- Use Cloudflare API tokens with minimal permissions.
- Query only supported datasets.
- Respect API limits.
- Handle missing metrics.
- Support multiple sites.
- Avoid mixing bot traffic with human visits.

Do not assume that all Web Analytics metrics are exposed by the same API endpoints as Zone Analytics.

## 10. Common Data Model

Normalize statistics into a consistent format.

Example:

```json
{
  "source": "ios",
  "metric": "first_time_downloads",
  "date": "2026-11-14",
  "value": 42,
  "unit": "downloads",
  "aggregation": "daily"
}
```

Each record should identify:

- Source
- Entity
- Metric
- Date or period
- Value
- Unit
- Aggregation type
- Collection timestamp
- Data quality status

Recommended statuses:

- confirmed
- estimated
- delayed
- unavailable

Avoid silently replacing missing values with zero.

## 11. Data Storage

Separate internal historical storage from public output.

Suggested structure:

```text
stats.avar.me/
├── README.md
├── config.yaml
├── requirements.txt
├── collectors/
│   ├── apple.py
│   ├── google_play.py
│   ├── telegram_channels.py
│   ├── telegram_bots.py
│   ├── telegram_stickers.py
│   └── cloudflare.py
├── integrations/
│   └── telegram_bot_analytics.py
├── scripts/
│   ├── collect.py
│   ├── aggregate.py
│   └── publish.py
├── data/
│   ├── history/
│   └── public/
│       ├── summary.json
│       └── history.json
├── site/
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── tests/
└── .github/
    └── workflows/
        └── update-stats.yml
```

The structure is a suggestion and can be adjusted.

### Storage Requirements

- Preserve historical data.
- Support incremental updates.
- Avoid duplicate records.
- Allow corrections to previously collected values.
- Support delayed reporting.
- Keep secrets and private information out of public JSON.
- Do not commit raw user-level telemetry.

## 12. Automation

Use GitHub Actions for scheduled collection.

Suggested schedule:

- Daily at 03:00 UTC

Workflow:

1. Fetch statistics from configured providers.
2. Validate API responses.
3. Normalize data.
4. Update historical storage.
5. Generate public JSON.
6. Deploy the static website.
7. Report collection failures.

A failure in one provider must not prevent other providers from updating.

Support manual workflow execution.

### Historical Backfill

Implement backfill where supported.

For sources without historical APIs, begin collecting snapshots from the deployment date.

Do not fabricate historical data.

## 13. Security

Store credentials in GitHub Actions Secrets or another secure secrets manager.

Never commit:

- Apple private keys
- Google service account credentials
- Telegram bot tokens
- Telegram MTProto credentials
- Cloudflare API tokens
- Raw user-level analytics

Use least-privilege API access.

Validate external API responses.

Avoid exposing internal infrastructure details unnecessarily.

## 14. Reliability and Monitoring

Each collector should report:

- Last successful execution
- Last attempted execution
- Number of records collected
- Errors
- Data freshness

The dashboard should distinguish:

- Successfully updated statistics
- Stale statistics
- Temporarily unavailable sources

A source failure should not reset its historical statistics.

Provide useful error messages in GitHub Actions logs without leaking secrets.

## 15. Testing

Implement automated tests for:

- Data normalization
- Duplicate prevention
- Aggregation
- Missing values
- API response parsing
- Historical backfill
- Public JSON generation
- Privacy filtering
- Collector failure isolation

Use mocked API responses.

Do not require production API credentials to run the test suite.

## 16. Documentation

Provide a README covering:

1. Project architecture
2. Local development
3. Configuration
4. Required credentials
5. API permissions
6. GitHub Actions setup
7. Cloudflare configuration
8. Telegram bot integration
9. Deployment
10. Troubleshooting

Document which metrics are supported, unavailable, or require additional instrumentation.

## 17. Implementation Phases

### Phase 1 — Foundation

- Create repository structure.
- Implement common data model.
- Build static dashboard.
- Add mock data for development.
- Implement public JSON generation.
- Configure deployment.

### Phase 2 — Telegram and Cloudflare

- Implement Telegram channel subscriber collection.
- Implement sticker pack metadata collection.
- Implement Cloudflare analytics.
- Configure daily snapshots.

### Phase 3 — Mobile Applications

- Integrate App Store Connect reports.
- Integrate Google Play reporting.
- Implement historical backfill where possible.

### Phase 4 — Telegram Bot Telemetry

- Investigate Telegram Serverless capabilities.
- Design lightweight instrumentation.
- Integrate analytics into bot handlers.
- Implement aggregation and reporting.

### Phase 5 — Production

- Add monitoring and error handling.
- Validate metrics against source dashboards.
- Configure GitHub Actions.
- Deploy stats.avar.me.
- Document limitations.

## 18. Acceptance Criteria

The project is complete when:

- stats.avar.me is publicly accessible.
- The website works on desktop and mobile.
- Each configured source has a dedicated statistics section.
- Available metrics update automatically.
- Historical charts display correctly.
- Missing metrics are clearly identified.
- Telegram bot statistics use real collected events.
- Sticker pack installation counts are not fabricated.
- Cloudflare traffic metrics are correctly labeled.
- No credentials or private user information are publicly exposed.
- Collection failures do not break the dashboard.
- Documentation explains setup and maintenance.

## 19. Instructions for the LLM Developer

Before implementing integrations:

1. Review official API documentation.
2. Verify which metrics are actually available.
3. Identify authentication and permission requirements.
4. Check reporting delays and historical limits.
5. Document unsupported metrics.
6. Prefer simple, maintainable solutions.

Do not implement fake production integrations.

Mock data may be used for frontend development but must be clearly separated from production data.

If an integration requires unavailable credentials or manual setup, implement the supported portion and document the exact steps needed to finish configuration.

Prioritize:

- Accuracy
- Simplicity
- Low operational cost
- Privacy
- Maintainability

The final result should be suitable for long-term public operation with minimal manual intervention.

