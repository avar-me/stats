/* Chrome strings live here so a future locale is another object, not a new layout.
   Metric names and definitions arrive in the published JSON. */
(function () {
  const I18N = {
    ru: {
      ranges: [
        ["7d", "7 дней"],
        ["30d", "30 дней"],
        ["90d", "90 дней"],
        ["1y", "Год"],
        ["all", "Всё время"],
      ],
      themeDark: "Тёмная тема",
      themeLight: "Светлая тема",
      loading: "Загрузка данных…",
      loadError: "Не удалось прочитать data/summary.json. Сначала выполните python scripts/publish.py.",
      updated: "Собрано",
      overview: "Сводка",
      noValue: "Нет данных",
      partial: "по {n} из {m}",
      windowFull: "{value} за {days} дней",
      windowPartial: "{value} за {present} из {expected} дней",
      windowEmpty: "За {days} дней данных нет",
      deltaExact: "{value} за {days} дней",
      deltaFrom: "{value} с {date}",
      deltaEmpty: "Сравнение появится после более раннего снимка",
      gapNote: "Пропуски в линии — дни без данных. Нулями они не заполняются.",
      snapshotNote: "Точки — дни, когда снимался показатель, а не восстановленные промежутки.",
      noPoints: "В выбранном периоде точек нет.",
      chartLabel: "График",
      tableLabel: "Таблица значений",
      date: "Дата",
      value: "Значение",
      status: "Состояние",
      countries: "Страны",
      devices: "Устройства",
      commands: "События",
      pages: "Страницы",
      referrers: "Источники переходов",
      breakdownWindow: "За окно последнего сбора, на",
      asOf: "на",
      stickersLink: "Открыть набор",
      delayed: "данные за этот день ещё могут измениться",
      estimated: "оценка",
      confirmed: "подтверждено",
      unavailable: "недоступно",
      statuses: {
        ok: "обновлено",
        stale: "устарело",
        not_configured: "не настроено",
        error: "ошибка сбора",
        disabled: "не подключено",
      },
      units: {
        subscribers: ["подписчик", "подписчика", "подписчиков"],
        stickers: ["стикер", "стикера", "стикеров"],
        views: ["просмотр", "просмотра", "просмотров"],
        visits: ["визит", "визита", "визитов"],
        requests: ["запрос", "запроса", "запросов"],
        downloads: ["загрузка", "загрузки", "загрузок"],
        users: ["пользователь", "пользователя", "пользователей"],
        devices: ["устройство", "устройства", "устройств"],
        ips: ["IP", "IP", "IP"],
        installs: ["установка", "установки", "установок"],
        milliseconds: ["мс", "мс", "мс"],
      },
    },
  };

  const state = { summary: null, history: null, range: "30d", charts: [] };
  const text = I18N.ru;
  const ranges = document.getElementById("ranges");
  const themeButton = document.getElementById("theme");
  const content = document.getElementById("content");

  text.ranges.forEach(function (item) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.range = item[0];
    button.textContent = item[1];
    button.setAttribute("role", "radio");
    button.setAttribute("aria-pressed", item[0] === state.range ? "true" : "false");
    ranges.appendChild(button);
  });

  ranges.addEventListener("click", function (event) {
    const button = event.target.closest("button[data-range]");
    if (!button) return;
    state.range = button.dataset.range;
    render();
  });

  themeButton.addEventListener("click", function () {
    const next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("stats-theme", next);
    render();
  });

  load();

  function load() {
    const base = new URLSearchParams(location.search).get("preview") === "1" ? "preview-data" : "data";
    Promise.all([
      fetch(base + "/summary.json").then(readJson),
      fetch(base + "/history.json").then(readJson),
    ]).then(function (pair) {
      state.summary = pair[0];
      state.history = pair[1];
      render();
    }).catch(function () {
      content.textContent = text.loadError;
    });
  }

  function readJson(response) {
    if (!response.ok) throw new Error(String(response.status));
    return response.json();
  }

  function render() {
    state.charts.forEach(function (chart) { chart.destroy(); });
    state.charts = [];
    syncControls();
    const summary = state.summary;
    document.getElementById("updated").textContent = summary.generated_at
      ? text.updated + " " + formatStamp(summary.generated_at)
      : "";
    document.getElementById("preview-banner").hidden = !summary.preview;
    content.replaceChildren();
    content.appendChild(sectionOverview(summary));
    summary.sources.forEach(function (source) {
      content.appendChild(sectionSource(source));
    });
  }

  function syncControls() {
    ranges.querySelectorAll("button").forEach(function (button) {
      button.setAttribute("aria-pressed", button.dataset.range === state.range ? "true" : "false");
    });
    const dark = currentTheme() === "dark";
    themeButton.setAttribute("aria-pressed", dark ? "true" : "false");
    themeButton.textContent = dark ? text.themeLight : text.themeDark;
    document.querySelector('meta[name="theme-color"]').setAttribute("content", dark ? "#14181d" : "#f4f1ea");
  }

  function currentTheme() {
    const explicit = document.documentElement.getAttribute("data-theme");
    if (explicit) return explicit;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function sectionOverview(summary) {
    const section = document.createElement("section");
    section.id = "overview";
    section.className = "overview";
    const heading = document.createElement("h2");
    heading.textContent = text.overview;
    const grid = document.createElement("div");
    grid.className = "cards";
    summary.cards.forEach(function (card) { grid.appendChild(renderCard(card)); });
    section.append(heading, grid);
    return section;
  }

  function renderCard(card) {
    const article = document.createElement("article");
    article.className = "card";
    const kicker = document.createElement("p");
    kicker.className = "fine";
    kicker.textContent = card.source_title;
    const title = document.createElement("h3");
    const link = document.createElement("a");
    link.href = card.href;
    link.textContent = card.title;
    title.appendChild(link);
    article.append(kicker, title, statusPill(card.status), valueLine(card.value, card.unit));
    if (card.partial) {
      const partial = document.createElement("p");
      partial.className = "fine";
      partial.textContent = fill(text.partial, { n: card.entities_with_value, m: card.entities });
      article.appendChild(partial);
    }
    const deltas = document.createElement("div");
    deltas.className = "deltas";
    deltas.appendChild(changeLine(card, 7));
    deltas.appendChild(changeLine(card, 30));
    article.append(deltas, definition(card.definition));
    if (card.updated_at) {
      const updated = document.createElement("p");
      updated.className = "fine";
      updated.textContent = formatStamp(card.updated_at);
      article.appendChild(updated);
    }
    return article;
  }

  function sectionSource(source) {
    const section = document.createElement("section");
    section.className = "source" + (source.enabled ? "" : " is-disabled");
    section.id = "source-" + source.id;
    const heading = document.createElement("h2");
    heading.textContent = source.title;
    section.append(heading, statusPill(source.status));
    if (source.message) section.appendChild(paragraph(source.message));
    if (source.hint) section.appendChild(paragraph(source.hint, "hint"));
    (source.warnings || []).forEach(function (warning) {
      section.appendChild(paragraph(warning, "fine"));
    });
    (source.unavailable || []).forEach(function (item) {
      const note = document.createElement("p");
      note.className = "notice";
      note.textContent = item.label + ". " + item.definition;
      section.appendChild(note);
    });
    if (!source.enabled) return section;
    source.entities.forEach(function (entity) {
      section.appendChild(renderEntity(source, entity));
    });
    return section;
  }

  function renderEntity(source, entity) {
    const block = document.createElement("article");
    block.className = "entity";
    const head = document.createElement("div");
    head.className = "entity-head";
    const title = document.createElement("h3");
    title.textContent = (entity.info && entity.info.title) || entity.title;
    head.appendChild(title);
    if (entity.link) {
      const link = document.createElement("a");
      link.href = safeLink(entity.link);
      link.textContent = entity.info && entity.info.url ? text.stickersLink : entity.link.replace("https://", "");
      head.appendChild(link);
    }
    block.appendChild(head);
    if (entity.message) block.appendChild(paragraph(entity.message, "fine"));
    if (!hasNumbers(entity)) return block;
    if (entity.info && entity.info.emojis) {
      const emojis = document.createElement("p");
      emojis.className = "emojis";
      emojis.textContent = entity.info.emojis;
      block.appendChild(emojis);
    }
    if (entity.info && entity.info.installs_note) {
      const note = document.createElement("p");
      note.className = "notice";
      note.textContent = entity.info.installs_note;
      block.appendChild(note);
    }
    const metrics = document.createElement("div");
    metrics.className = "metrics";
    entity.metrics.forEach(function (metric) {
      if (metric.metric === "duration_ms_sum" || metric.metric === "duration_count" || metric.metric === "command_requests") return;
      metrics.appendChild(renderMetric(entity, metric));
    });
    block.appendChild(metrics);
    const derived = derivedLines(entity);
    if (derived) block.appendChild(derived);
    entity.metrics.forEach(function (metric) {
      if (metric.metric === "command_requests") {
        appendDimension(block, metric, "command", text.commands);
        return;
      }
      if (!metric.series || !state.history.series[metric.series]) return;
      block.appendChild(renderChart(metric));
      appendDimension(block, metric, "country", text.countries);
      appendDimension(block, metric, "device", text.devices);
    });
    (entity.breakdowns || []).forEach(function (breakdown) {
      const label = breakdown.dimension === "path" ? text.pages : text.referrers;
      block.appendChild(simpleTable(
        label + ". " + text.breakdownWindow + " " + formatDate(breakdown.as_of),
        breakdown.rows.map(function (row) { return [row.label, formatNumber(row.value)]; })
      ));
    });
    return block;
  }

  function hasNumbers(entity) {
    return entity.metrics.some(function (metric) { return metric.latest != null; })
      || (entity.breakdowns || []).length > 0
      || (entity.info && (entity.info.emojis || entity.info.installs_note));
  }

  function renderMetric(entity, metric) {
    const card = document.createElement("article");
    card.className = "card";
    const title = document.createElement("h3");
    title.textContent = metric.label;
    card.append(title, valueLine(metric.latest, metric.unit));
    if (metric.latest_date) card.appendChild(paragraph(text.asOf + " " + formatDate(metric.latest_date), "fine"));
    if (metric.latest_status && metric.latest_status !== "confirmed") {
      card.appendChild(paragraph(text[metric.latest_status] || metric.latest_status, "fine"));
    }
    const deltas = document.createElement("div");
    deltas.className = "deltas";
    deltas.append(changeLine(metric, 7), changeLine(metric, 30));
    card.append(deltas, definition(metric.definition));
    return card;
  }

  function renderChart(metric) {
    const wrap = document.createElement("div");
    wrap.className = "chart-card";
    const heading = document.createElement("h3");
    heading.textContent = metric.label;
    const end = metric.latest_date || state.summary.generated_at.slice(0, 10);
    const points = (state.history.series[metric.series] || []).filter(function (point) {
      return inRange(point.date, state.range, end);
    });
    wrap.appendChild(heading);
    if (!points.length) {
      wrap.appendChild(paragraph(text.noPoints, "fine"));
      return wrap;
    }
    const canvas = document.createElement("canvas");
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", text.chartLabel + ": " + metric.label);
    wrap.appendChild(canvas);
    wrap.appendChild(paragraph(metric.kind === "snapshot" ? text.snapshotNote : text.gapNote, "fine"));
    wrap.appendChild(dataTable(points, metric));
    requestAnimationFrame(function () { drawChart(canvas, points, metric); });
    return wrap;
  }

  function drawChart(canvas, points, metric) {
    if (typeof Chart === "undefined" || !canvas.isConnected) return;
    const drawn = metric.kind === "snapshot" ? points : withGaps(points);
    const color = cssVar("--chart") || "#9a7b1a";
    const grid = cssVar("--chart-grid") || "rgba(0,0,0,.08)";
    const label = cssVar("--text-muted") || "#5a6570";
    const chart = new Chart(canvas, {
      type: "line",
      data: {
        labels: drawn.map(function (point) { return point ? formatDate(point.date) : ""; }),
        datasets: [{
          label: metric.label,
          data: drawn.map(function (point) { return point ? point.value : null; }),
          borderColor: color,
          backgroundColor: color,
          pointRadius: metric.kind === "snapshot" ? 3 : 0,
          tension: 0,
          spanGaps: false,
        }],
      },
      options: {
        animation: false,
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { filter: function (item) { return item.raw !== null; } },
        },
        scales: {
          x: { ticks: { color: label, maxRotation: 0, autoSkip: true, maxTicksLimit: 6 }, grid: { color: grid } },
          y: { beginAtZero: metric.kind === "flow", ticks: { color: label }, grid: { color: grid } },
        },
      },
    });
    state.charts.push(chart);
  }

  function appendDimension(block, metric, dimension, label) {
    const end = metric.latest_date || state.summary.generated_at.slice(0, 10);
    const rows = ranked(metric.series, dimension, end);
    if (!rows.length) return;
    block.appendChild(simpleTable(label, rows.map(function (row) {
      return [row.label, formatNumber(row.value)];
    })));
  }

  function ranked(seriesId, dimension, end) {
    const prefix = seriesId + "|" + dimension + "=";
    const rows = [];
    Object.keys(state.history.series).forEach(function (key) {
      if (!key.startsWith(prefix)) return;
      const points = state.history.series[key].filter(function (point) {
        return inRange(point.date, state.range, end);
      });
      if (!points.length) return;
      rows.push({
        label: key.slice(prefix.length),
        value: points.reduce(function (total, point) { return total + point.value; }, 0),
      });
    });
    rows.sort(function (a, b) { return b.value - a.value; });
    return rows.slice(0, 8);
  }

  function derivedLines(entity) {
    const byName = {};
    entity.metrics.forEach(function (metric) { byName[metric.metric] = metric; });
    const lines = [];
    if (byName.failed_requests && byName.requests && byName.requests.latest) {
      const rate = Math.round((byName.failed_requests.latest / byName.requests.latest) * 1000) / 10;
      lines.push("Доля неуспешных в последний день: " + String(rate).replace(".", ",") + "%");
    }
    if (byName.duration_ms_sum && byName.duration_count && byName.duration_count.latest) {
      const avg = Math.round(byName.duration_ms_sum.latest / byName.duration_count.latest);
      lines.push("Среднее время обработки в последний день: " + formatNumber(avg) + " мс");
    }
    if (!lines.length) return null;
    return paragraph(lines.join(". "), "fine");
  }

  function dataTable(points, metric) {
    const rows = points.slice(-14).map(function (point) {
      return [formatDate(point.date), formatNumber(point.value), text[point.status] || point.status];
    });
    return simpleTable(text.tableLabel + ": " + metric.label, rows, [text.date, text.value, text.status]);
  }

  function simpleTable(captionText, rows, headers) {
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    const table = document.createElement("table");
    const cap = document.createElement("caption");
    cap.textContent = captionText;
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    (headers || ["Название", text.value]).forEach(function (label) {
      headRow.appendChild(cell(label, "th"));
    });
    head.appendChild(headRow);
    const body = document.createElement("tbody");
    rows.forEach(function (row) {
      const tr = document.createElement("tr");
      row.forEach(function (value) { tr.appendChild(cell(value, "td")); });
      body.appendChild(tr);
    });
    table.append(cap, head, body);
    wrap.appendChild(table);
    return wrap;
  }

  function cell(value, tag) {
    const node = document.createElement(tag);
    node.textContent = value == null ? "" : String(value);
    return node;
  }

  function changeLine(metric, days) {
    const line = document.createElement("p");
    line.className = "fine";
    if (metric.kind === "flow") {
      const windowValue = metric["window_" + days + "d"];
      line.textContent = windowText(windowValue, days, metric.unit);
      return line;
    }
    const delta = metric["delta_" + days + "d"];
    const from = metric["delta_" + days + "d_from"];
    if (delta == null) {
      line.textContent = days + " дн.: " + text.deltaEmpty;
      return line;
    }
    const end = metric.as_of || metric.latest_date;
    const exact = end && from && dayDiff(end, from) === days;
    const formatted = signed(delta) + " " + plural(delta, metric.unit);
    line.textContent = exact
      ? fill(text.deltaExact, { value: formatted, days: days })
      : fill(text.deltaFrom, { value: formatted, date: formatDate(from) });
    line.classList.add(delta > 0 ? "up" : delta < 0 ? "down" : "fine");
    return line;
  }

  function windowText(windowValue, days, unit) {
    if (!windowValue) return fill(text.windowEmpty, { days: days });
    const value = formatNumber(windowValue.sum) + " " + plural(windowValue.sum, unit);
    if (windowValue.days_present === windowValue.days_expected) return fill(text.windowFull, { value: value, days: days });
    return fill(text.windowPartial, {
      value: value,
      present: windowValue.days_present,
      expected: windowValue.days_expected,
    });
  }

  function valueLine(value, unit) {
    const node = document.createElement("p");
    node.className = "value";
    node.textContent = value == null ? text.noValue : formatNumber(value) + " " + plural(value, unit);
    return node;
  }

  function statusPill(status) {
    const node = document.createElement("p");
    node.className = "status status-" + status;
    node.textContent = text.statuses[status] || status;
    return node;
  }

  function definition(copy) {
    const node = document.createElement("p");
    node.className = "definition";
    node.textContent = copy;
    return node;
  }

  function paragraph(copy, className) {
    const node = document.createElement("p");
    if (className) node.className = className;
    node.textContent = copy;
    return node;
  }

  function withGaps(points) {
    const sorted = points.slice().sort(function (a, b) { return a.date.localeCompare(b.date); });
    const out = [];
    sorted.forEach(function (point, index) {
      if (index > 0) {
        const delta = (Date.parse(point.date + "T00:00:00Z") - Date.parse(sorted[index - 1].date + "T00:00:00Z")) / 86400000;
        if (delta > 1.5) out.push(null);
      }
      out.push(point);
    });
    return out;
  }

  function inRange(iso, range, endIso) {
    if (range === "all") return true;
    const days = { "7d": 7, "30d": 30, "90d": 90, "1y": 365 }[range];
    const end = Date.parse(endIso + "T00:00:00Z");
    const point = Date.parse(iso + "T00:00:00Z");
    return point >= end - (days - 1) * 86400000 && point <= end;
  }

  function dayDiff(later, earlier) {
    return Math.round((Date.parse(later + "T00:00:00Z") - Date.parse(earlier + "T00:00:00Z")) / 86400000);
  }

  function plural(value, unit) {
    const forms = text.units[unit] || [unit, unit, unit];
    const number = Math.abs(Number(value));
    const mod100 = number % 100;
    const mod10 = number % 10;
    if (mod100 > 10 && mod100 < 20) return forms[2];
    if (mod10 > 1 && mod10 < 5) return forms[1];
    if (mod10 === 1) return forms[0];
    return forms[2];
  }

  function signed(value) {
    const number = formatNumber(value);
    if (value > 0) return "+" + number;
    return number;
  }

  function formatNumber(value) {
    return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(value);
  }

  function formatDate(iso) {
    if (!iso) return "";
    const parts = iso.split("-");
    return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })
      .format(new Date(Date.UTC(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))));
  }

  function formatStamp(iso) {
    return new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(new Date(iso)) + " UTC";
  }

  function fill(template, values) {
    return template.replace(/\{(\w+)\}/g, function (_, key) { return values[key]; });
  }

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function safeLink(url) {
    try {
      const parsed = new URL(url);
      if (parsed.protocol === "https:") return parsed.href;
    } catch (error) { /* keep the page on a bad link */ }
    return "#";
  }
})();
