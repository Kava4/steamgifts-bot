(() => {
  const TAB_META = {
    activity: {
      title: "Activity",
      subtitle: "Giveaway entries and bot status",
    },
    entered: {
      title: "Entered",
      subtitle: "Open giveaways you joined",
    },
    wins: {
      title: "Wins",
      subtitle: "Giveaways you have won",
    },
    console: {
      title: "Console",
      subtitle: "Full event log",
    },
    settings: {
      title: "Settings",
      subtitle: "Accounts and bot behavior",
    },
  };

  const BADGE = {
    entered: "ENTERED",
    won: "WON",
    waiting: "WAITING",
    prompt: "SELECT",
    skipped: "SKIPPED",
    info: "INFO",
    error: "ERROR",
  };

  const els = {
    statusPill: document.getElementById("statusPill"),
    countdownLabel: document.getElementById("countdownLabel"),
    pointsValue: document.getElementById("pointsValue"),
    pageValue: document.getElementById("pageValue"),
    contentHeader: document.getElementById("contentHeader"),
    contentSubheader: document.getElementById("contentSubheader"),
    contentBalances: document.getElementById("contentBalances"),
    activityFeed: document.getElementById("activityFeed"),
    activityEmpty: document.getElementById("activityEmpty"),
    enteredFeed: document.getElementById("enteredFeed"),
    enteredEmpty: document.getElementById("enteredEmpty"),
    winsFeed: document.getElementById("winsFeed"),
    winsEmpty: document.getElementById("winsEmpty"),
    consoleLog: document.getElementById("consoleLog"),
    fetchPointsBtn: document.getElementById("fetchPointsBtn"),
    startBtn: document.getElementById("startBtn"),
    stopBtn: document.getElementById("stopBtn"),
    clearLogsBtn: document.getElementById("clearLogsBtn"),
    manualSelectCheckbox: document.getElementById("manualSelectCheckbox"),
    refreshEnteredBtn: document.getElementById("refreshEnteredBtn"),
    cookieInput: document.getElementById("cookieInput"),
    showCookieBtn: document.getElementById("showCookieBtn"),
    saveCookieBtn: document.getElementById("saveCookieBtn"),
    enableIndiegalaCheckbox: document.getElementById("enableIndiegalaCheckbox"),
    indiegalaCookieInput: document.getElementById("indiegalaCookieInput"),
    testIndiegalaBtn: document.getElementById("testIndiegalaBtn"),
    saveIndiegalaBtn: document.getElementById("saveIndiegalaBtn"),
    refreshCombo: document.getElementById("refreshCombo"),
    maxPagesSpin: document.getElementById("maxPagesSpin"),
    maxEndHoursSpin: document.getElementById("maxEndHoursSpin"),
    indiegalaDelaySpin: document.getElementById("indiegalaDelaySpin"),
    indiegalaMinCostSpin: document.getElementById("indiegalaMinCostSpin"),
    notifyOnWinCheckbox: document.getElementById("notifyOnWinCheckbox"),
    toast: document.getElementById("toast"),
  };

  let running = false;
  let cookieVisible = false;
  let applyingSettings = false;
  let points = null;
  let silver = null;
  let username = "";
  let countdownTimer = null;
  let countdownSeconds = 0;
  let countdownBaseLabel = "";

  function toast(message, isError = false) {
    els.toast.textContent = message;
    els.toast.classList.toggle("error", isError);
    els.toast.classList.remove("hidden");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => els.toast.classList.add("hidden"), 3200);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    let data = null;
    const text = await response.text();
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = { detail: text };
      }
    }
    if (!response.ok) {
      const detail = (data && data.detail) || response.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return data;
  }

  function setRunning(isRunning) {
    running = isRunning;
    els.statusPill.textContent = isRunning ? "RUNNING" : "STOPPED";
    els.statusPill.classList.toggle("running", isRunning);
    els.statusPill.classList.toggle("stopped", !isRunning);
    els.startBtn.disabled = isRunning;
    els.stopBtn.disabled = !isRunning;
    els.cookieInput.disabled = isRunning;
    els.saveCookieBtn.disabled = isRunning;
    els.indiegalaCookieInput.disabled = isRunning;
    els.saveIndiegalaBtn.disabled = isRunning;
    els.testIndiegalaBtn.disabled = isRunning;
    els.enableIndiegalaCheckbox.disabled = isRunning;
    if (!isRunning) {
      stopCountdown();
    }
  }

  function updateBalances() {
    const parts = [];
    if (points != null) parts.push(`${points}P`);
    if (silver != null) parts.push(`${silver} iS`);
    if (username) parts.push(username);
    if (parts.length) {
      els.contentBalances.textContent = parts.join(" · ");
      els.contentBalances.classList.remove("hidden");
    } else {
      els.contentBalances.classList.add("hidden");
    }
    els.pointsValue.textContent = points != null ? String(points) : "-";
  }

  function stopCountdown() {
    if (countdownTimer) {
      clearInterval(countdownTimer);
      countdownTimer = null;
    }
    countdownSeconds = 0;
    countdownBaseLabel = "";
    els.countdownLabel.classList.add("hidden");
    els.countdownLabel.textContent = "";
  }

  function renderCountdown() {
    if (countdownSeconds <= 0) {
      stopCountdown();
      return;
    }
    const mins = Math.floor(countdownSeconds / 60);
    const secs = countdownSeconds % 60;
    const clock = `${mins}:${String(secs).padStart(2, "0")}`;
    const label = countdownBaseLabel ? `${countdownBaseLabel} · ${clock}` : clock;
    els.countdownLabel.textContent = label;
    els.countdownLabel.classList.remove("hidden");
  }

  function setCountdown(label, seconds) {
    stopCountdown();
    countdownBaseLabel = label || "";
    countdownSeconds = Math.max(0, Number(seconds) || 0);
    if (countdownSeconds <= 0) return;
    renderCountdown();
    countdownTimer = setInterval(() => {
      countdownSeconds -= 1;
      renderCountdown();
    }, 1000);
  }

  function badgeText(card) {
    if (card.status === "entered" && card.source === "indiegala") return "INDIEGALA";
    if (card.status === "won" && card.source === "indiegala") return "INDIEGALA WIN";
    return BADGE[card.status] || String(card.status || "INFO").toUpperCase();
  }

  function cardImage(url) {
    if (!url) return `<div class="card-image">…</div>`;
    return `<div class="card-image"><img src="${escapeAttr(url)}" alt="" loading="lazy" /></div>`;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/'/g, "&#39;");
  }

  function createCardElement(card) {
    const status = card.status || "info";
    const wrapper = document.createElement("div");
    wrapper.className = `activity-card ${status}`;
    if (card.code) wrapper.dataset.code = card.code;

    const ends = card.ends_text
      ? `<div class="card-ends">${escapeHtml(card.ends_text)}</div>`
      : "";

    let actions = "";
    if (card.kind === "prompt" || status === "prompt") {
      actions = `
        <div class="card-actions">
          <button class="btn accent" data-manual="yes" type="button">Yes</button>
          <button class="btn danger" data-manual="no" type="button">No</button>
        </div>`;
    }

    if (card.kind === "entered" || card.xsrf_token) {
      actions = `
        <div class="card-actions">
          <button class="btn danger" data-remove="${escapeAttr(card.code)}" data-xsrf="${escapeAttr(card.xsrf_token)}" type="button">Remove</button>
        </div>`;
    }

    const link =
      card.url
        ? `<a class="card-subtitle" href="${escapeAttr(card.url)}" target="_blank" rel="noopener">${escapeHtml(card.subtitle || card.url)}</a>`
        : `<div class="card-subtitle">${escapeHtml(card.subtitle || "")}</div>`;

    wrapper.innerHTML = `
      ${cardImage(card.image_url)}
      <div class="card-body">
        <div class="card-top">
          <div class="card-title">${escapeHtml(card.title || card.name || "")}</div>
          <div class="card-badge">${escapeHtml(badgeText(card))}</div>
        </div>
        ${link}
        ${ends}
        ${card.entries_count != null ? `<div class="card-meta">${escapeHtml(card.entries_count)} entries · ${escapeHtml(card.entered_label || "")}</div>` : ""}
        ${actions}
      </div>`;

    wrapper.querySelectorAll("[data-manual]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const enter = btn.getAttribute("data-manual") === "yes";
        wrapper.querySelectorAll("[data-manual]").forEach((b) => {
          b.disabled = true;
        });
        const badge = wrapper.querySelector(".card-badge");
        if (badge) badge.textContent = enter ? "ENTERED" : "SKIPPED";
        wrapper.classList.remove("prompt");
        wrapper.classList.add(enter ? "entered" : "skipped");
        try {
          await api("/api/manual", {
            method: "POST",
            body: JSON.stringify({ enter }),
          });
        } catch (error) {
          toast(error.message, true);
        }
      });
    });

    wrapper.querySelectorAll("[data-remove]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await api(`/api/entered/${encodeURIComponent(btn.dataset.remove)}/remove`, {
            method: "POST",
            body: JSON.stringify({ xsrf_token: btn.dataset.xsrf }),
          });
          wrapper.remove();
          syncEmpty(els.enteredFeed, els.enteredEmpty);
          toast("Entry removed");
        } catch (error) {
          btn.disabled = false;
          toast(error.message, true);
        }
      });
    });

    return wrapper;
  }

  function syncEmpty(feed, empty) {
    const hasCards = feed.children.length > 0;
    empty.classList.toggle("hidden", hasCards);
  }

  function renderActivity(cards) {
    els.activityFeed.innerHTML = "";
    (cards || []).forEach((card) => {
      els.activityFeed.appendChild(createCardElement(card));
    });
    syncEmpty(els.activityFeed, els.activityEmpty);
  }

  function appendActivity(card) {
    // Drop waiting cards when a real card arrives
    if (card.status !== "waiting") {
      [...els.activityFeed.querySelectorAll(".activity-card.waiting")].forEach((node) =>
        node.remove()
      );
    }
    els.activityFeed.appendChild(createCardElement(card));
    syncEmpty(els.activityFeed, els.activityEmpty);
    els.activityFeed.parentElement.scrollTop = els.activityFeed.parentElement.scrollHeight;
  }

  function upsertWaiting(card) {
    const existing = els.activityFeed.querySelector(".activity-card.waiting");
    const node = createCardElement(card);
    if (existing) {
      existing.replaceWith(node);
    } else {
      els.activityFeed.prepend(node);
    }
    syncEmpty(els.activityFeed, els.activityEmpty);
  }

  function clearWaiting() {
    [...els.activityFeed.querySelectorAll(".activity-card.waiting")].forEach((node) =>
      node.remove()
    );
    syncEmpty(els.activityFeed, els.activityEmpty);
  }

  function renderConsole(lines) {
    els.consoleLog.textContent = (lines || []).join("\n");
    els.consoleLog.scrollTop = els.consoleLog.scrollHeight;
  }

  function appendConsole(line) {
    if (els.consoleLog.textContent) {
      els.consoleLog.textContent += `\n${line}`;
    } else {
      els.consoleLog.textContent = line;
    }
    els.consoleLog.scrollTop = els.consoleLog.scrollHeight;
  }

  function renderWins(wins) {
    els.winsFeed.innerHTML = "";
    (wins || []).forEach((win) => {
      els.winsFeed.appendChild(
        createCardElement({
          title: win.name,
          subtitle: win.source === "indiegala" ? "IndieGala win" : "SteamGifts win",
          image_url: win.image_url,
          status: "won",
          source: win.source,
          url: win.url,
        })
      );
    });
    syncEmpty(els.winsFeed, els.winsEmpty);
  }

  function renderEntered(items) {
    els.enteredFeed.innerHTML = "";
    (items || []).forEach((item) => {
      els.enteredFeed.appendChild(
        createCardElement({
          kind: "entered",
          title: item.name,
          subtitle: `${item.cost}P`,
          image_url: item.image_url,
          status: "entered",
          ends_text: item.ends_text || item.remaining_label,
          code: item.code,
          xsrf_token: item.xsrf_token,
          entries_count: item.entries_count,
          entered_label: item.entered_label,
        })
      );
    });
    syncEmpty(els.enteredFeed, els.enteredEmpty);
  }

  function applySettings(settings) {
    if (!settings) return;
    applyingSettings = true;
    els.manualSelectCheckbox.checked = !!settings.manual_select_giveaways;
    els.enableIndiegalaCheckbox.checked = !!settings.enable_indiegala_beta;
    els.notifyOnWinCheckbox.checked = settings.notify_on_win !== false;
    els.refreshCombo.value = String(settings.refresh_delay_minutes ?? 10);
    els.maxPagesSpin.value = settings.max_pages ?? 5;
    els.maxEndHoursSpin.value = settings.max_giveaway_end_hours ?? 3;
    els.indiegalaDelaySpin.value = settings.indiegala_entry_delay ?? 5;
    els.indiegalaMinCostSpin.value = settings.indiegala_min_cost ?? 0;
    applyingSettings = false;
  }

  async function saveSettingsPatch(patch) {
    if (applyingSettings) return;
    try {
      const settings = await api("/api/settings", {
        method: "POST",
        body: JSON.stringify(patch),
      });
      applySettings(settings);
    } catch (error) {
      toast(error.message, true);
    }
  }

  function applySnapshot(snap) {
    setRunning(!!snap.running);
    points = snap.points;
    silver = snap.silver;
    username = snap.username || "";
    updateBalances();
    els.pageValue.textContent = snap.page != null ? String(snap.page) : "-";
    applySettings(snap.settings);
    renderActivity(snap.activity || []);
    renderConsole(snap.console || []);
    renderWins(snap.wins || []);
    if (snap.countdown_seconds > 0) {
      setCountdown(snap.countdown_label || "", snap.countdown_seconds);
    } else {
      stopCountdown();
    }
  }

  function handleEvent(event) {
    switch (event.type) {
      case "snapshot":
        applySnapshot(event);
        break;
      case "log":
        appendConsole(event.message);
        break;
      case "activity":
        appendActivity(event.card);
        break;
      case "waiting":
        upsertWaiting(event.card);
        break;
      case "waiting_clear":
        clearWaiting();
        break;
      case "prompt":
        appendActivity(event.card);
        break;
      case "cleared":
        renderActivity([]);
        renderConsole([]);
        break;
      case "status":
        if (event.source === "indiegala") {
          if (event.silver != null) silver = event.silver;
          else if (event.points != null) silver = event.points;
        } else if (event.points != null) {
          points = event.points;
        }
        if (event.silver != null) silver = event.silver;
        if (event.username) username = event.username;
        if (event.page != null) els.pageValue.textContent = String(event.page);
        updateBalances();
        break;
      case "countdown":
        setCountdown(event.label || "", event.seconds || 0);
        break;
      case "running":
        setRunning(!!event.running);
        if (!event.running) stopCountdown();
        break;
      case "settings":
        applySettings(event.settings);
        break;
      case "wins":
        renderWins(event.wins || []);
        break;
      default:
        break;
    }
  }

  function connectWs() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.addEventListener("message", (msg) => {
      try {
        handleEvent(JSON.parse(msg.data));
      } catch (error) {
        console.error(error);
      }
    });
    ws.addEventListener("close", () => {
      setTimeout(connectWs, 1500);
    });
  }

  // Tabs
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const name = tab.dataset.tab;
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
      document.querySelectorAll(".tab-panel").forEach((panel) => {
        panel.classList.toggle("active", panel.id === `panel-${name}`);
      });
      const meta = TAB_META[name];
      if (meta) {
        els.contentHeader.textContent = meta.title;
        els.contentSubheader.textContent = meta.subtitle;
      }
      if (name === "entered") {
        refreshEntered();
      }
      if (name === "wins") {
        api("/api/wins").then(renderWins).catch((error) => toast(error.message, true));
      }
    });
  });

  els.fetchPointsBtn.addEventListener("click", async () => {
    els.fetchPointsBtn.disabled = true;
    try {
      const data = await api("/api/points", { method: "POST", body: "{}" });
      points = data.points;
      silver = data.silver;
      username = data.username || "";
      updateBalances();
      toast(`Logged in as ${username}`);
    } catch (error) {
      toast(error.message, true);
    } finally {
      els.fetchPointsBtn.disabled = false;
    }
  });

  els.startBtn.addEventListener("click", async () => {
    try {
      await api("/api/bot/start", { method: "POST", body: "{}" });
      setRunning(true);
    } catch (error) {
      toast(error.message, true);
    }
  });

  els.stopBtn.addEventListener("click", async () => {
    try {
      await api("/api/bot/stop", { method: "POST", body: "{}" });
      setRunning(false);
    } catch (error) {
      toast(error.message, true);
    }
  });

  els.clearLogsBtn.addEventListener("click", async () => {
    try {
      await api("/api/logs/clear", { method: "POST", body: "{}" });
    } catch (error) {
      toast(error.message, true);
    }
  });

  els.manualSelectCheckbox.addEventListener("change", () => {
    saveSettingsPatch({ manual_select_giveaways: els.manualSelectCheckbox.checked });
  });

  els.enableIndiegalaCheckbox.addEventListener("change", () => {
    saveSettingsPatch({ enable_indiegala_beta: els.enableIndiegalaCheckbox.checked });
  });

  els.notifyOnWinCheckbox.addEventListener("change", () => {
    saveSettingsPatch({ notify_on_win: els.notifyOnWinCheckbox.checked });
  });

  els.refreshCombo.addEventListener("change", () => {
    saveSettingsPatch({ refresh_delay_minutes: Number(els.refreshCombo.value) });
  });

  els.maxPagesSpin.addEventListener("change", () => {
    saveSettingsPatch({ max_pages: Number(els.maxPagesSpin.value) });
  });

  els.maxEndHoursSpin.addEventListener("change", () => {
    saveSettingsPatch({ max_giveaway_end_hours: Number(els.maxEndHoursSpin.value) });
  });

  els.indiegalaDelaySpin.addEventListener("change", () => {
    saveSettingsPatch({ indiegala_entry_delay: Number(els.indiegalaDelaySpin.value) });
  });

  els.indiegalaMinCostSpin.addEventListener("change", () => {
    saveSettingsPatch({ indiegala_min_cost: Number(els.indiegalaMinCostSpin.value) });
  });

  els.showCookieBtn.addEventListener("click", () => {
    cookieVisible = !cookieVisible;
    els.cookieInput.type = cookieVisible ? "text" : "password";
    els.showCookieBtn.textContent = cookieVisible ? "Hide" : "Show";
  });

  els.saveCookieBtn.addEventListener("click", async () => {
    try {
      await api("/api/cookies", {
        method: "POST",
        body: JSON.stringify({ cookie: els.cookieInput.value }),
      });
      toast("Cookie saved");
    } catch (error) {
      toast(error.message, true);
    }
  });

  els.saveIndiegalaBtn.addEventListener("click", async () => {
    try {
      const data = await api("/api/cookies", {
        method: "POST",
        body: JSON.stringify({ indiegala_cookie: els.indiegalaCookieInput.value }),
      });
      if (data.indiegala_cookie) {
        els.indiegalaCookieInput.value = data.indiegala_cookie;
      }
      toast("IndieGala cookie saved");
    } catch (error) {
      toast(error.message, true);
    }
  });

  els.testIndiegalaBtn.addEventListener("click", async () => {
    try {
      const data = await api("/api/indiegala/test", {
        method: "POST",
        body: JSON.stringify({ cookie: els.indiegalaCookieInput.value }),
      });
      silver = data.silver;
      updateBalances();
      toast(`IndieGala OK · ${data.username}`);
    } catch (error) {
      toast(error.message, true);
    }
  });

  async function refreshEntered() {
    els.refreshEnteredBtn.disabled = true;
    try {
      const items = await api("/api/entered");
      renderEntered(items);
    } catch (error) {
      toast(error.message, true);
    } finally {
      els.refreshEnteredBtn.disabled = false;
    }
  }

  els.refreshEnteredBtn.addEventListener("click", refreshEntered);

  async function loadCookies() {
    try {
      const data = await api("/api/cookies");
      els.cookieInput.value = data.cookie || "";
      els.indiegalaCookieInput.value = data.indiegala_cookie || "";
    } catch (error) {
      toast(error.message, true);
    }
  }

  loadCookies();
  connectWs();
})();
