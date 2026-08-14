/* QuickAI front end. Vanilla JS, no build step, no dependencies. */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const el = {
    statusBtn: $("statusBtn"), statusDot: $("statusDot"), statusText: $("statusText"),
    modelSelect: $("modelSelect"), refreshModels: $("refreshModels"),
    themeBtn: $("themeBtn"), settingsBtn: $("settingsBtn"),
    actionBar: $("actionBar"), actionMenuBtn: $("actionMenuBtn"),
    actionMenu: $("actionMenu"), actionSearch: $("actionSearch"),
    actionMenuList: $("actionMenuList"), actionCount: $("actionCount"),
    currentActionText: $("currentActionText"),
    panes: $("panes"), inputStageBtn: $("inputStageBtn"), outputStageBtn: $("outputStageBtn"),
    input: $("input"), inputMeta: $("inputMeta"),
    pasteBtn: $("pasteBtn"), clearBtn: $("clearBtn"),
    output: $("output"), outputMeta: $("outputMeta"),
    stopBtn: $("stopBtn"), againBtn: $("againBtn"),
    chainBtn: $("chainBtn"), copyBtn: $("copyBtn"),
    followForm: $("followForm"), followInput: $("followInput"),
    toast: $("toast"),
    settings: $("settings"), closeSettings: $("closeSettings"),
    cancelSettings: $("cancelSettings"), saveSettings: $("saveSettings"),
    cfgBaseUrl: $("cfgBaseUrl"), cfgApiKey: $("cfgApiKey"), keyHint: $("keyHint"),
    removeKey: $("removeKey"),
    cfgModelsPath: $("cfgModelsPath"), cfgChatPath: $("cfgChatPath"),
    cfgExtraBody: $("cfgExtraBody"),
    cfgTemp: $("cfgTemp"), tempVal: $("tempVal"),
    cfgMaxTokens: $("cfgMaxTokens"), cfgTimeout: $("cfgTimeout"),
    cfgAutoCopy: $("cfgAutoCopy"), cfgFont: $("cfgFont"), fontVal: $("fontVal"),
    cfgPathNote: $("cfgPathNote"),
    actList: $("actList"), actLabel: $("actLabel"), actIcon: $("actIcon"),
    actGroup: $("actGroup"), actSystem: $("actSystem"), actTemplate: $("actTemplate"),
    actTemp: $("actTemp"), actDelete: $("actDelete"),
    actNew: $("actNew"), actReset: $("actReset"),
  };

  const state = {
    cfg: null,
    actions: [],
    current: null,        // action id highlighted in the bar
    lastRun: null,        // { actionId, input } for the Again button
    turns: [],            // [{role, content}] for follow-ups
    result: "",
    controller: null,     // AbortController for the live request
    draftActions: [],     // working copy inside the settings modal
    editingId: null,
    settingsDirty: false,
    removeApiKey: false,
  };

  /* ─────────────────────────────── helpers ─────────────────────────────── */

  async function api(path, options = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
      throw new Error(detail);
    }
    return res.status === 204 ? null : res.json();
  }

  let toastTimer;
  function toast(message, ms = 2000) {
    el.toast.textContent = message;
    el.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.toast.hidden = true; }, ms);
  }

  async function copy(text) {
    if (!text) return false;
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Clipboard API needs a secure context; fall back to the old trick.
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch { ok = false; }
      ta.remove();
      return ok;
    }
  }

  function renderMarkdown(text) {
    if (!window.marked || !window.DOMPurify) {
      el.output.textContent = text;
      return;
    }
    el.output.innerHTML = DOMPurify.sanitize(marked.parse(text));
    if (window.renderMathInElement) {
      renderMathInElement(el.output, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "$", right: "$", display: false },
          { left: "\\(", right: "\\)", display: false },
          { left: "\\[", right: "\\]", display: true },
        ],
        throwOnError: false,
        trust: false,
      });
    }
  }

  const setTheme = (theme) => {
    document.documentElement.dataset.theme = theme;
  };

  const setFont = (px) => {
    document.documentElement.style.setProperty("--editor-size", `${px}px`);
  };

  function actionMark(action) {
    const saved = (action.icon || "").trim();
    if (/^[a-z0-9]{1,2}$/i.test(saved)) return saved.toUpperCase();
    const words = (action.label || "AI").match(/[a-z0-9]+/gi) || ["AI"];
    return words.slice(0, 2).map((word) => word[0]).join("").toUpperCase();
  }

  /* ──────────────────────────────── boot ───────────────────────────────── */

  async function boot() {
    try {
      state.cfg = await api("/api/config");
    } catch (err) {
      el.output.classList.add("err");
      el.output.textContent = `Cannot talk to the QuickAI service: ${err.message}`;
      return;
    }
    state.actions = state.cfg.actions || [];
    setTheme(state.cfg.ui?.theme || "dark");
    setFont(state.cfg.ui?.font_size || 15);
    state.current = state.cfg.ui?.last_action || (state.actions[0] && state.actions[0].id);
    renderActions();
    updateInputMeta();
    await Promise.all([loadModels(false), checkHealth()]);
    el.input.focus();
  }

  /* ─────────────────────────────── status ──────────────────────────────── */

  async function checkHealth() {
    el.statusDot.className = "dot busy";
    el.statusText.textContent = "checking…";
    try {
      const data = await api("/api/health");
      if (data.llm.ok) {
        el.statusDot.className = "dot ok";
        el.statusText.textContent = `${data.llm.count} models`;
        el.statusBtn.title = "LLM API connected";
      } else {
        el.statusDot.className = "dot bad";
        el.statusText.textContent = "LLM unavailable";
        el.statusBtn.title = data.llm.error || "";
      }
    } catch (err) {
      el.statusDot.className = "dot bad";
      el.statusText.textContent = "service error";
      el.statusBtn.title = err.message;
    }
  }

  async function loadModels(refresh) {
    el.modelSelect.innerHTML = "";
    try {
      const data = await api(`/api/models${refresh ? "?refresh=true" : ""}`);
      if (!data.models.length) {
        el.modelSelect.appendChild(new Option("no models found", ""));
        return;
      }
      for (const name of data.models) {
        el.modelSelect.appendChild(new Option(name, name));
      }
      el.modelSelect.value = data.selected || data.models[0];
    } catch (err) {
      el.modelSelect.appendChild(new Option("model list unavailable", ""));
      el.modelSelect.title = err.message;
    }
  }

  /* ──────────────────────────── action bar ─────────────────────────────── */

  function actionButton(action, compact = false) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = compact
      ? "chip" + (action.id === state.current ? " is-on" : "")
      : "menuAction" + (action.id === state.current ? " is-on" : "");
    button.dataset.id = action.id;

    const marker = document.createElement("span");
    marker.className = "ic";
    marker.textContent = actionMark(action);
    button.append(marker, document.createTextNode(action.label));

    const index = state.actions.indexOf(action);
    if (compact && index < 9) {
      const kb = document.createElement("span");
      kb.className = "kb";
      kb.textContent = `Alt+${index + 1}`;
      button.appendChild(kb);
    }
    button.addEventListener("click", () => {
      closeActionMenu();
      run(action.id);
    });
    return button;
  }

  function renderActions() {
    el.actionBar.innerHTML = "";
    el.actionCount.textContent = state.actions.length;

    const current = state.actions.find((action) => action.id === state.current);
    const favorites = [current, ...state.actions]
      .filter((action, index, list) => action && list.indexOf(action) === index)
      .slice(0, 5);
    for (const action of favorites) el.actionBar.appendChild(actionButton(action, true));

    const selected = current || state.actions[0];
    el.currentActionText.textContent = selected ? selected.label : "Choose an action";
    renderActionMenu(el.actionSearch.value);
  }

  function renderActionMenu(query = "") {
    el.actionMenuList.innerHTML = "";
    const needle = query.trim().toLowerCase();
    const matches = state.actions.filter((action) =>
      `${action.label} ${action.group} ${action.id}`.toLowerCase().includes(needle)
    );
    let lastGroup = null;
    for (const action of matches) {
      if (action.group !== lastGroup) {
        const group = document.createElement("span");
        group.className = "menuGroup";
        group.textContent = action.group || "Actions";
        el.actionMenuList.appendChild(group);
      }
      lastGroup = action.group;
      el.actionMenuList.appendChild(actionButton(action));
    }
    if (!matches.length) {
      const empty = document.createElement("p");
      empty.className = "menuEmpty";
      empty.textContent = "No matching actions";
      el.actionMenuList.appendChild(empty);
    }
  }

  function closeActionMenu() {
    el.actionMenu.hidden = true;
    el.actionMenuBtn.setAttribute("aria-expanded", "false");
  }

  function highlight(actionId) {
    state.current = actionId;
    renderActions();
  }

  function setMobileStage(stage) {
    el.panes.dataset.mobileStage = stage;
    const input = stage === "input";
    el.inputStageBtn.classList.toggle("is-on", input);
    el.outputStageBtn.classList.toggle("is-on", !input);
    el.inputStageBtn.setAttribute("aria-selected", String(input));
    el.outputStageBtn.setAttribute("aria-selected", String(!input));
  }

  /* ───────────────────────────────── run ───────────────────────────────── */

  function setBusy(busy) {
    el.stopBtn.hidden = !busy;
    for (const button of document.querySelectorAll(".chip, .menuAction, #actionMenuBtn")) {
      button.disabled = busy;
    }
  }

  function finishOutput(text, isError) {
    state.result = text;
    el.output.classList.toggle("err", !!isError);
    const hasResult = !!text && !isError;
    el.againBtn.hidden = !hasResult;
    el.copyBtn.hidden = !hasResult;
    el.chainBtn.hidden = !hasResult;
    el.followForm.hidden = !hasResult;
  }

  async function run(actionId, opts = {}) {
    const followUp = opts.followUp || null;
    const text = followUp ?? el.input.value;

    if (!followUp && !text.trim()) {
      toast("Nothing in the input box");
      el.input.focus();
      return;
    }
    if (state.controller) state.controller.abort();

    highlight(actionId);
    if (!followUp) {
      state.turns = [];
      state.lastRun = { actionId, input: text };
    }

    setMobileStage("output");
    el.output.textContent = "";
    el.output.classList.remove("err");
    const caret = document.createElement("span");
    caret.className = "caret";
    el.output.appendChild(caret);
    el.outputMeta.textContent = followUp ? "following up…" : "thinking…";
    finishOutput("", false);
    setBusy(true);

    const started = performance.now();
    let acc = "";
    let promptSent = "";
    let errored = false;

    state.controller = new AbortController();
    try {
      const res = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: state.controller.signal,
        body: JSON.stringify({
          action_id: actionId,
          input: text,
          model: el.modelSelect.value || null,
          history: state.turns,
          raw: !!followUp,
        }),
      });

      if (!res.ok) {
        let detail = res.statusText;
        try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
        throw new Error(detail);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let cut;
        while ((cut = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, cut).trim();
          buffer = buffer.slice(cut + 2);
          if (!frame.startsWith("data:")) continue;

          let event;
          try { event = JSON.parse(frame.slice(5).trim()); } catch { continue; }

          if (event.type === "start") {
            promptSent = event.prompt || text;
          } else if (event.type === "delta") {
            acc += event.text;
            caret.remove();
            renderMarkdown(acc);
            el.output.appendChild(caret);
            el.output.scrollTop = el.output.scrollHeight;
          } else if (event.type === "error") {
            errored = true;
            caret.remove();
            el.output.textContent = event.message;
            finishOutput(event.message, true);
            el.outputMeta.textContent = "failed";
          }
        }
      }
    } catch (err) {
      caret.remove();
      if (err.name === "AbortError") {
        el.outputMeta.textContent = acc ? "stopped" : "cancelled";
        finishOutput(acc, false);
        setBusy(false);
        state.controller = null;
        return;
      }
      errored = true;
      el.output.textContent = err.message;
      finishOutput(err.message, true);
      el.outputMeta.textContent = "failed";
    }

    caret.remove();
    state.controller = null;
    setBusy(false);

    if (errored) return;

    renderMarkdown(acc);
    finishOutput(acc, false);
    state.turns.push({ role: "user", content: promptSent || text });
    state.turns.push({ role: "assistant", content: acc });

    const seconds = ((performance.now() - started) / 1000).toFixed(1);
    el.outputMeta.textContent = `${acc.length} chars · ${seconds}s`;

    if (state.cfg?.ui?.auto_copy && acc) {
      if (await copy(acc)) toast("Copied to clipboard");
    }
  }

  /* ─────────────────────────── input / output ──────────────────────────── */

  function updateInputMeta() {
    const value = el.input.value;
    const words = value.trim() ? value.trim().split(/\s+/).length : 0;
    el.inputMeta.textContent = `${value.length} chars · ${words} words`;
  }

  el.input.addEventListener("input", updateInputMeta);

  el.actionMenuBtn.addEventListener("click", () => {
    const open = el.actionMenu.hidden;
    el.actionMenu.hidden = !open;
    el.actionMenuBtn.setAttribute("aria-expanded", String(open));
    if (open) {
      el.actionSearch.value = "";
      renderActionMenu();
      el.actionSearch.focus();
    }
  });
  el.actionSearch.addEventListener("input", () => renderActionMenu(el.actionSearch.value));
  document.addEventListener("mousedown", (event) => {
    if (!el.actionMenu.hidden && !event.target.closest(".actions")) closeActionMenu();
  });

  el.inputStageBtn.addEventListener("click", () => {
    setMobileStage("input");
    el.input.focus();
  });
  el.outputStageBtn.addEventListener("click", () => setMobileStage("output"));

  el.pasteBtn.addEventListener("click", async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (!text) return toast("Clipboard is empty");
      el.input.value = text;
      updateInputMeta();
      el.input.focus();
    } catch {
      toast("Browser blocked clipboard read — use Ctrl+V");
      el.input.focus();
    }
  });

  el.clearBtn.addEventListener("click", () => {
    el.input.value = "";
    updateInputMeta();
    el.input.focus();
  });

  el.copyBtn.addEventListener("click", async () => {
    toast(await copy(state.result) ? "Copied" : "Copy failed — select and press Ctrl+C");
  });

  el.chainBtn.addEventListener("click", () => {
    el.input.value = state.result;
    updateInputMeta();
    setMobileStage("input");
    el.input.focus();
    toast("Result moved to input");
  });

  el.againBtn.addEventListener("click", () => {
    if (!state.lastRun) return;
    el.input.value = state.lastRun.input;
    run(state.lastRun.actionId);
  });

  el.stopBtn.addEventListener("click", () => state.controller && state.controller.abort());

  el.followForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = el.followInput.value.trim();
    if (!text) return;
    el.followInput.value = "";
    run(state.current, { followUp: text });
  });

  el.statusBtn.addEventListener("click", checkHealth);
  el.refreshModels.addEventListener("click", async () => {
    await loadModels(true);
    await checkHealth();
    toast("Model list reloaded");
  });

  el.modelSelect.addEventListener("change", async () => {
    await api("/api/config", {
      method: "PUT",
      body: JSON.stringify({ model: el.modelSelect.value }),
    });
    toast(`Model: ${el.modelSelect.value}`);
  });

  el.themeBtn.addEventListener("click", async () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    setTheme(next);
    state.cfg.ui.theme = next;
    await api("/api/config", { method: "PUT", body: JSON.stringify({ ui: { theme: next } }) });
  });

  /* ──────────────────────────── keyboard ───────────────────────────────── */

  document.addEventListener("keydown", (event) => {
    const inModal = !el.settings.hidden;

    if (event.key === "Escape") {
      if (!el.actionMenu.hidden) { closeActionMenu(); el.actionMenuBtn.focus(); return; }
      if (inModal) { closeSettings(); return; }
      if (state.controller) { state.controller.abort(); return; }
    }
    if (inModal) {
      if (event.key === "Tab") trapSettingsFocus(event);
      return;
    }

    // Alt+1..9 → nth action
    if (event.altKey && !event.ctrlKey && !event.metaKey && /^[1-9]$/.test(event.key)) {
      const action = state.actions[Number(event.key) - 1];
      if (action) { event.preventDefault(); run(action.id); }
      return;
    }
    const mod = event.ctrlKey || event.metaKey;
    if (mod && event.key === "Enter") {
      event.preventDefault();
      run(state.current || (state.actions[0] && state.actions[0].id));
      return;
    }
    if (mod && event.shiftKey && event.key.toLowerCase() === "c") {
      if (!state.result) return;
      event.preventDefault();
      copy(state.result).then((ok) => toast(ok ? "Copied" : "Copy failed"));
      return;
    }
    if (mod && event.shiftKey && event.key.toLowerCase() === "x") {
      event.preventDefault();
      el.input.value = "";
      updateInputMeta();
      el.input.focus();
      return;
    }
    if (mod && event.key === ",") {
      event.preventDefault();
      openSettings();
    }
  });

  /* ──────────────────────────── settings ───────────────────────────────── */

  function openSettings() {
    const cfg = state.cfg;
    el.cfgBaseUrl.value = cfg.base_url || "";
    el.cfgApiKey.value = "";
    el.keyHint.textContent = cfg.has_api_key
      ? "A key is saved. Type a new key to replace it."
      : "No key saved.";
    el.removeKey.hidden = !cfg.has_api_key;
    el.cfgModelsPath.value = cfg.models_path || "/v1/models";
    el.cfgChatPath.value = cfg.chat_path || "/v1/chat/completions";
    el.cfgExtraBody.value = cfg.extra_body && Object.keys(cfg.extra_body).length
      ? JSON.stringify(cfg.extra_body, null, 2) : "";
    el.cfgTemp.value = cfg.temperature ?? 0.3;
    el.tempVal.textContent = Number(el.cfgTemp.value).toFixed(2);
    el.cfgMaxTokens.value = cfg.max_tokens ?? "";
    el.cfgTimeout.value = cfg.request_timeout ?? 300;
    el.cfgAutoCopy.checked = !!cfg.ui?.auto_copy;
    el.cfgFont.value = cfg.ui?.font_size ?? 15;
    el.fontVal.textContent = el.cfgFont.value;
    el.cfgPathNote.textContent = "Saved outside the repo, in ~/.config/quickai/config.json";

    state.draftActions = JSON.parse(JSON.stringify(state.actions));
    state.editingId = state.draftActions[0]?.id || null;
    state.removeApiKey = false;
    renderActionEditor();

    el.settings.hidden = false;
    state.settingsDirty = false;
    el.cfgBaseUrl.focus();
  }

  function closeSettings(force = false) {
    if (!force && state.settingsDirty && !confirm("Discard unsaved settings?")) return false;
    if (!force && state.settingsDirty) setFont(state.cfg.ui?.font_size || 15);
    el.settings.hidden = true;
    state.settingsDirty = false;
    el.input.focus();
    return true;
  }

  function trapSettingsFocus(event) {
    const focusable = [...el.settings.querySelectorAll(
      "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])"
    )].filter((node) => node.getClientRects().length);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  el.settingsBtn.addEventListener("click", openSettings);
  el.closeSettings.addEventListener("click", () => closeSettings());
  el.cancelSettings.addEventListener("click", () => closeSettings());
  el.settings.addEventListener("mousedown", (event) => {
    if (event.target === el.settings) closeSettings();
  });
  el.settings.addEventListener("input", (event) => {
    if (event.target.matches("input, textarea, select")) state.settingsDirty = true;
  });

  el.removeKey.addEventListener("click", () => {
    state.removeApiKey = true;
    state.settingsDirty = true;
    el.cfgApiKey.value = "";
    el.removeKey.hidden = true;
    el.keyHint.textContent = "Saved key will be removed when you save.";
  });

  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => {
      for (const other of document.querySelectorAll(".tab")) {
        other.classList.toggle("is-on", other === tab);
        other.setAttribute("aria-selected", String(other === tab));
      }
      for (const pane of document.querySelectorAll(".tabPane")) {
        const selected = pane.dataset.pane === tab.dataset.tab;
        pane.classList.toggle("is-on", selected);
        pane.hidden = !selected;
      }
    });
  }

  el.cfgTemp.addEventListener("input", () => {
    el.tempVal.textContent = Number(el.cfgTemp.value).toFixed(2);
  });
  el.cfgFont.addEventListener("input", () => {
    el.fontVal.textContent = el.cfgFont.value;
    setFont(el.cfgFont.value);
  });

  el.saveSettings.addEventListener("click", async () => {
    stashEdits();
    let extra = {};
    const rawExtra = el.cfgExtraBody.value.trim();
    if (rawExtra) {
      try {
        extra = JSON.parse(rawExtra);
        if (typeof extra !== "object" || Array.isArray(extra)) throw new Error();
      } catch {
        toast("Extra request body must be a JSON object", 3200);
        return;
      }
    }

    const patch = {
      base_url: el.cfgBaseUrl.value.trim(),
      models_path: el.cfgModelsPath.value.trim() || "/v1/models",
      chat_path: el.cfgChatPath.value.trim() || "/v1/chat/completions",
      extra_body: extra,
      temperature: Number(el.cfgTemp.value),
      max_tokens: el.cfgMaxTokens.value ? Number(el.cfgMaxTokens.value) : null,
      request_timeout: Number(el.cfgTimeout.value) || 300,
      ui: {
        auto_copy: el.cfgAutoCopy.checked,
        font_size: Number(el.cfgFont.value),
      },
    };
    if (state.removeApiKey) patch.api_key = "";
    else if (el.cfgApiKey.value.trim()) patch.api_key = el.cfgApiKey.value.trim();

    try {
      await api("/api/actions", {
        method: "PUT",
        body: JSON.stringify({ actions: state.draftActions }),
      });
      state.cfg = await api("/api/config", { method: "PUT", body: JSON.stringify(patch) });
      state.actions = state.cfg.actions || [];
      if (!state.actions.some((a) => a.id === state.current)) {
        state.current = state.actions[0]?.id || null;
      }
      renderActions();
      state.settingsDirty = false;
      closeSettings(true);
      toast("Saved");
      await Promise.all([loadModels(true), checkHealth()]);
    } catch (err) {
      toast(`Save failed: ${err.message}`, 4000);
    }
  });

  /* ───────────────────────── action editor ─────────────────────────────── */

  function renderActionEditor() {
    el.actList.innerHTML = "";
    for (const action of state.draftActions) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "actItem" + (action.id === state.editingId ? " is-on" : "");
      item.innerHTML = `<span class="actMark"></span><span></span>`;
      item.children[0].textContent = actionMark(action);
      item.children[1].textContent = action.label;
      if (!action.builtin) {
        const tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = "custom";
        item.appendChild(tag);
      }
      item.addEventListener("click", () => {
        stashEdits();
        state.editingId = action.id;
        renderActionEditor();
      });
      el.actList.appendChild(item);
    }
    fillActionForm();
  }

  const currentDraft = () => state.draftActions.find((a) => a.id === state.editingId);

  function fillActionForm() {
    const action = currentDraft();
    const disabled = !action;
    for (const node of [el.actLabel, el.actIcon, el.actGroup, el.actSystem, el.actTemplate, el.actTemp]) {
      node.disabled = disabled;
    }
    el.actDelete.disabled = disabled;
    if (!action) {
      for (const node of [el.actLabel, el.actIcon, el.actGroup, el.actSystem, el.actTemplate, el.actTemp]) {
        node.value = "";
      }
      return;
    }
    el.actLabel.value = action.label || "";
    el.actIcon.value = actionMark(action);
    el.actGroup.value = action.group || "Custom";
    el.actSystem.value = action.system || "";
    el.actTemplate.value = action.template || "{input}";
    el.actTemp.value = action.temperature ?? "";
  }

  function stashEdits() {
    const action = currentDraft();
    if (!action) return;
    action.label = el.actLabel.value.trim() || action.label;
    action.icon = /^[a-z0-9]{1,2}$/i.test(el.actIcon.value.trim())
      ? el.actIcon.value.trim().toUpperCase()
      : actionMark(action);
    action.group = el.actGroup.value.trim() || "Custom";
    action.system = el.actSystem.value;
    action.template = el.actTemplate.value || "{input}";
    action.temperature = el.actTemp.value === "" ? null : Number(el.actTemp.value);
  }

  el.actNew.addEventListener("click", () => {
    stashEdits();
    const id = `custom-${Date.now().toString(36)}`;
    state.draftActions.push({
      id,
      label: "New action",
      icon: "NA",
      group: "Custom",
      system:
        "You are a precise assistant. Return ONLY the requested output — no " +
        "preamble, no explanation, no markdown fences.",
      template: "{input}",
      temperature: null,
      builtin: false,
    });
    state.settingsDirty = true;
    state.editingId = id;
    renderActionEditor();
    el.actLabel.focus();
    el.actLabel.select();
  });

  el.actDelete.addEventListener("click", () => {
    const action = currentDraft();
    if (!action) return;
    if (state.draftActions.length === 1) return toast("Keep at least one action");
    if (!confirm(`Delete “${action.label}”?`)) return;
    state.draftActions = state.draftActions.filter((a) => a.id !== action.id);
    state.settingsDirty = true;
    state.editingId = state.draftActions[0]?.id || null;
    renderActionEditor();
  });

  el.actReset.addEventListener("click", async () => {
    if (!confirm("Restore built-in prompts in this draft? Your custom actions stay.")) return;
    try {
      stashEdits();
      const data = await api("/api/actions/defaults");
      const custom = state.draftActions.filter((action) => !action.builtin);
      state.draftActions = data.actions.concat(custom);
      state.editingId = state.draftActions[0]?.id || null;
      state.settingsDirty = true;
      renderActionEditor();
    } catch (err) {
      toast(`Failed: ${err.message}`, 3500);
    }
  });

  boot();
})();
