(() => {
  "use strict";

  const form = document.querySelector("#chat-form");
  const input = document.querySelector("#message-input");
  const sendButton = document.querySelector("#send-button");
  const chatLog = document.querySelector("#chat-log");
  const welcomePanel = document.querySelector("#welcome-panel");
  const providerSelect = document.querySelector("#provider-select");
  const sidebar = document.querySelector("#conversation-sidebar");
  const sidebarToggle = document.querySelector("#sidebar-toggle");
  const sidebarBackdrop = document.querySelector("#sidebar-backdrop");
  const newConversationButton = document.querySelector("#new-conversation-button");
  const conversationList = document.querySelector("#conversation-list");
  const conversationCount = document.querySelector("#conversation-count");
  const historyEmpty = document.querySelector("#history-empty");
  const currentConversationTitle = document.querySelector("#current-conversation-title");

  let sessionId = null;
  let conversations = [];
  let pending = false;
  let pendingDeleteId = null;

  function createSessionId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return `web-${window.crypto.randomUUID()}`;
    }
    return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function createElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  async function requestJson(url, options = {}) {
    const response = await fetch(url, options);
    const payload = response.status === 204
      ? null
      : await response.json().catch(() => null);
    if (!response.ok) {
      const error = new Error(payload?.error?.message || "请求失败，请稍后重试。");
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function weatherIcon(condition) {
    if (/雷/.test(condition)) return "⛈";
    if (/雪/.test(condition)) return "❄";
    if (/雨/.test(condition)) return "☂";
    if (/雾|霾/.test(condition)) return "≋";
    if (/阴/.test(condition)) return "☁";
    if (/云/.test(condition)) return "☁";
    if (/晴/.test(condition)) return "☀";
    return "◌";
  }

  function appendUserMessage(message) {
    const item = createElement("li", "message message-user");
    item.appendChild(createElement("p", "message-bubble", message));
    chatLog.appendChild(item);
    scrollToLatest();
  }

  function appendWeatherMessage(payload) {
    const item = createElement("li", "message message-agent");
    const card = createElement("article", "weather-card");
    card.setAttribute("aria-label", `${payload.city}${payload.date}天气`);

    const header = createElement("div", "weather-card-header");
    const place = createElement("div", "weather-place");
    place.appendChild(createElement("span", "weather-icon", weatherIcon(payload.weather.condition)));
    const placeText = createElement("div", "weather-place-text");
    placeText.appendChild(createElement("strong", "", payload.city));
    placeText.appendChild(createElement("span", "", payload.date));
    place.appendChild(placeText);
    header.appendChild(place);
    header.appendChild(createElement("span", "provider-badge", providerName(payload.provider)));

    const overview = createElement("div", "weather-overview");
    overview.appendChild(createElement("strong", "temperature", `${formatNumber(payload.weather.temperature_c)}°`));
    const conditionBlock = createElement("div", "condition-block");
    conditionBlock.appendChild(createElement("strong", "", payload.weather.condition));
    conditionBlock.appendChild(createElement("span", "", "体感信息以当前数据源为准"));
    overview.appendChild(conditionBlock);

    const metrics = createElement("dl", "weather-metrics");
    appendMetric(metrics, "湿度", `${payload.weather.humidity_percent}%`);
    appendMetric(metrics, "风速", `${formatNumber(payload.weather.wind_speed_mps)} m/s`);
    appendMetric(metrics, "降雨", payload.weather.rain_expected ? "有可能" : "暂无");

    card.appendChild(header);
    card.appendChild(overview);
    card.appendChild(metrics);

    if (payload.weather.advice) {
      const advice = createElement("p", "weather-advice");
      advice.appendChild(createElement("span", "advice-mark", "建议"));
      advice.appendChild(document.createTextNode(payload.weather.advice));
      card.appendChild(advice);
    }
    if (payload.mode !== "agent") {
      card.appendChild(createElement("p", "weather-answer", payload.answer));
    }
    item.appendChild(card);
    chatLog.appendChild(item);
    scrollToLatest();
  }

  function appendAgentText(answer) {
    const item = createElement("li", "message message-agent");
    item.appendChild(createElement("p", "message-bubble agent-text-bubble", answer));
    chatLog.appendChild(item);
    scrollToLatest();
  }

  function appendAgentResponse(payload) {
    if (payload.display_mode === "text") {
      appendAgentText(payload.answer);
      return;
    }
    if (payload.mode === "agent") appendAgentText(payload.answer);
    const results = Array.isArray(payload.results) && payload.results.length
      ? payload.results
      : [payload];
    results.forEach((result) => {
      appendWeatherMessage({
        ...payload,
        ...result,
        weather: result.weather || payload.weather,
      });
    });
  }

  function appendMetric(list, label, value) {
    const metric = createElement("div", "weather-metric");
    metric.appendChild(createElement("dt", "", label));
    metric.appendChild(createElement("dd", "", value));
    list.appendChild(metric);
  }

  function appendError(message) {
    const item = createElement("li", "message message-agent");
    const bubble = createElement("div", "message-bubble error-bubble");
    bubble.appendChild(createElement("strong", "", "暂时没查到"));
    bubble.appendChild(createElement("span", "", message));
    item.appendChild(bubble);
    chatLog.appendChild(item);
    scrollToLatest();
  }

  function appendLoading() {
    const item = createElement("li", "message message-agent loading-message");
    item.setAttribute("aria-label", "Agent 正在思考");
    const bubble = createElement("div", "message-bubble typing-indicator");
    for (let index = 0; index < 3; index += 1) bubble.appendChild(createElement("span"));
    item.appendChild(bubble);
    chatLog.appendChild(item);
    scrollToLatest();
    return item;
  }

  function providerName(provider) {
    const names = {
      qweather: "和风天气",
      openweather: "OpenWeather",
      openmeteo: "Open-Meteo",
      weatherapi: "WeatherAPI.com",
      visualcrossing: "Visual Crossing",
    };
    return names[provider] || provider;
  }

  function formatNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(1) : "--";
  }

  function formatConversationTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "刚刚";
    return new Intl.DateTimeFormat("zh-CN", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  }

  function scrollToLatest() {
    window.requestAnimationFrame(() => {
      chatLog.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "end" });
    });
  }

  function resizeInput() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
  }

  function setPending(value) {
    pending = value;
    input.disabled = value;
    sendButton.disabled = value;
    providerSelect.disabled = value;
    newConversationButton.disabled = value;
    conversationList.setAttribute("aria-busy", String(value));
    sendButton.querySelector("span:first-child").textContent = value ? "思考中" : "发送";
  }

  function renderConversationList() {
    conversationList.replaceChildren();
    conversationCount.textContent = String(conversations.length);
    historyEmpty.hidden = conversations.length > 0;

    conversations.forEach((conversation) => {
      const item = createElement("li", "conversation-item");
      if (conversation.id === sessionId) item.classList.add("is-active");

      const selectButton = createElement("button", "conversation-select");
      selectButton.type = "button";
      selectButton.dataset.conversationId = conversation.id;
      if (conversation.id === sessionId) selectButton.setAttribute("aria-current", "page");
      selectButton.appendChild(createElement("span", "conversation-title", conversation.title));
      selectButton.appendChild(createElement(
        "span",
        "conversation-meta",
        `${formatConversationTime(conversation.updated_at)} · ${conversation.message_count / 2} 轮`,
      ));

      const isConfirmingDelete = conversation.id === pendingDeleteId;
      const deleteButton = createElement(
        "button",
        `conversation-delete${isConfirmingDelete ? " is-confirming" : ""}`,
        isConfirmingDelete ? "确认" : "×",
      );
      deleteButton.type = "button";
      deleteButton.dataset.deleteConversationId = conversation.id;
      deleteButton.setAttribute(
        "aria-label",
        `${isConfirmingDelete ? "确认删除" : "删除"}对话：${conversation.title}`,
      );
      deleteButton.title = isConfirmingDelete ? "再次点击确认删除" : "删除对话";
      item.appendChild(selectButton);
      item.appendChild(deleteButton);
      conversationList.appendChild(item);
    });
  }

  function setActiveConversation(conversation) {
    sessionId = conversation.id;
    currentConversationTitle.textContent = conversation.title;
    renderConversationList();
  }

  function renderConversation(conversation) {
    setActiveConversation(conversation);
    chatLog.replaceChildren();
    const messages = Array.isArray(conversation.messages) ? conversation.messages : [];
    welcomePanel.hidden = messages.length > 0;
    messages.forEach((message) => {
      if (message.role === "user") appendUserMessage(message.content);
      else if (message.payload) appendAgentResponse(message.payload);
      else appendAgentText(message.content);
    });
  }

  async function refreshConversations(activeId = sessionId) {
    const payload = await requestJson("/api/conversations");
    conversations = Array.isArray(payload.conversations) ? payload.conversations : [];
    if (activeId) {
      sessionId = activeId;
      const active = conversations.find((item) => item.id === activeId);
      if (active) currentConversationTitle.textContent = active.title;
    }
    renderConversationList();
  }

  async function createConversation() {
    pendingDeleteId = null;
    const payload = await requestJson("/api/conversations", { method: "POST" });
    const conversation = payload.conversation;
    conversations = [conversation, ...conversations.filter((item) => item.id !== conversation.id)];
    renderConversation(conversation);
    closeSidebar();
    input.focus();
    return conversation;
  }

  async function startNewConversation() {
    if (pending || newConversationButton.disabled) return;
    newConversationButton.disabled = true;
    try {
      await createConversation();
    } catch (error) {
      appendError(error.message);
    } finally {
      newConversationButton.disabled = pending;
    }
  }

  async function openConversation(conversationId) {
    if (pending) return;
    pendingDeleteId = null;
    if (conversationId === sessionId) {
      renderConversationList();
      closeSidebar();
      return;
    }
    try {
      const payload = await requestJson(`/api/conversations/${conversationId}`);
      renderConversation(payload.conversation);
      closeSidebar();
      input.focus();
    } catch (error) {
      renderConversationList();
      appendError(error.message);
    }
  }

  async function deleteConversation(conversationId) {
    if (pending) return;
    const target = conversations.find((item) => item.id === conversationId);
    if (!target) return;
    if (pendingDeleteId !== conversationId) {
      pendingDeleteId = conversationId;
      renderConversationList();
      return;
    }

    try {
      pendingDeleteId = null;
      await requestJson(`/api/conversations/${conversationId}`, { method: "DELETE" });
      conversations = conversations.filter((item) => item.id !== conversationId);
      if (sessionId === conversationId) {
        if (conversations.length > 0) await openConversation(conversations[0].id);
        else await createConversation();
      } else {
        renderConversationList();
      }
    } catch (error) {
      renderConversationList();
      appendError(error.message);
    }
  }

  function openSidebar() {
    sidebar.classList.add("is-open");
    sidebarBackdrop.classList.add("is-visible");
    sidebarToggle.setAttribute("aria-expanded", "true");
    sidebarToggle.setAttribute("aria-label", "关闭历史对话栏");
    newConversationButton.focus();
  }

  function closeSidebar() {
    sidebar.classList.remove("is-open");
    sidebarBackdrop.classList.remove("is-visible");
    sidebarToggle.setAttribute("aria-expanded", "false");
    sidebarToggle.setAttribute("aria-label", "打开历史对话栏");
  }

  async function sendMessage(message) {
    if (pending) return;
    if (!sessionId) {
      try {
        await createConversation();
      } catch (_error) {
        sessionId = createSessionId();
      }
    }

    welcomePanel.hidden = true;
    appendUserMessage(message);
    input.value = "";
    resizeInput();
    setPending(true);
    const loadingMessage = appendLoading();
    let displayError = "网络连接失败，请稍后再试。";

    try {
      const response = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, session_id: sessionId, provider: providerSelect.value }),
      });
      const payload = await response.json().catch(() => null);
      loadingMessage.remove();
      if (!payload) {
        displayError = "天气服务返回了无法识别的数据，请稍后再试。";
        throw new Error("invalid response");
      }
      if (!response.ok) {
        displayError = payload.error?.message || "天气服务暂时不可用，请稍后再试。";
        throw new Error("request failed");
      }
      sessionId = payload.session_id || sessionId;
      appendAgentResponse(payload);
      try {
        await refreshConversations(sessionId);
      } catch (_historyError) {
        currentConversationTitle.textContent = message.slice(0, 36);
      }
    } catch (_error) {
      loadingMessage.remove();
      appendError(displayError);
    } finally {
      setPending(false);
      input.focus();
    }
  }

  async function initializeConversations() {
    historyEmpty.textContent = "正在加载历史对话…";
    try {
      await refreshConversations();
      if (conversations.length > 0) {
        const payload = await requestJson(`/api/conversations/${conversations[0].id}`);
        renderConversation(payload.conversation);
      } else {
        await createConversation();
      }
    } catch (_error) {
      sessionId = createSessionId();
      historyEmpty.hidden = false;
      historyEmpty.textContent = "历史对话暂时无法加载";
      currentConversationTitle.textContent = "临时对话";
    }
    input.focus();
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const message = input.value.trim();
    if (message) void sendMessage(message);
  });
  input.addEventListener("input", resizeInput);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  newConversationButton.addEventListener("click", () => {
    void startNewConversation();
  });
  conversationList.addEventListener("click", (event) => {
    const deleteButton = event.target.closest("[data-delete-conversation-id]");
    if (deleteButton) {
      void deleteConversation(deleteButton.dataset.deleteConversationId);
      return;
    }
    const selectButton = event.target.closest("[data-conversation-id]");
    if (selectButton) void openConversation(selectButton.dataset.conversationId);
  });
  sidebarToggle.addEventListener("click", () => {
    if (sidebar.classList.contains("is-open")) closeSidebar();
    else openSidebar();
  });
  sidebarBackdrop.addEventListener("click", closeSidebar);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && sidebar.classList.contains("is-open")) {
      closeSidebar();
      sidebarToggle.focus();
    }
  });
  document.querySelectorAll("[data-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      const prompt = button.getAttribute("data-prompt");
      if (prompt) {
        input.value = prompt;
        resizeInput();
        form.requestSubmit();
      }
    });
  });

  void initializeConversations();
})();
