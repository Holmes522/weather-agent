(() => {
  "use strict";

  const form = document.querySelector("#chat-form");
  const input = document.querySelector("#message-input");
  const sendButton = document.querySelector("#send-button");
  const chatLog = document.querySelector("#chat-log");
  const welcomePanel = document.querySelector("#welcome-panel");
  const providerSelect = document.querySelector("#provider-select");

  let sessionId = createSessionId();
  let pending = false;

  function createSessionId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return `web-${window.crypto.randomUUID()}`;
    }
    return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function createElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) {
      element.className = className;
    }
    if (text !== undefined) {
      element.textContent = text;
    }
    return element;
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
    const bubble = createElement("p", "message-bubble", message);
    item.appendChild(bubble);
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
    overview.appendChild(
      createElement("strong", "temperature", `${formatNumber(payload.weather.temperature_c)}°`),
    );
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

    card.appendChild(createElement("p", "weather-answer", payload.answer));
    item.appendChild(card);
    chatLog.appendChild(item);
    scrollToLatest();
  }

  function appendAgentText(answer) {
    const item = createElement("li", "message message-agent");
    const bubble = createElement("p", "message-bubble agent-text-bubble", answer);
    item.appendChild(bubble);
    chatLog.appendChild(item);
    scrollToLatest();
  }

  function appendAgentResponse(payload) {
    if (payload.display_mode === "text") {
      appendAgentText(payload.answer);
      return;
    }

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
    item.setAttribute("aria-label", "正在查询天气");
    const bubble = createElement("div", "message-bubble typing-indicator");
    for (let index = 0; index < 3; index += 1) {
      bubble.appendChild(createElement("span"));
    }
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
    sendButton.querySelector("span:first-child").textContent = value ? "查询中" : "发送";
  }

  async function sendMessage(message) {
    if (pending) return;

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
        body: JSON.stringify({
          message,
          session_id: sessionId,
          provider: providerSelect.value,
        }),
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
    } catch (_error) {
      loadingMessage.remove();
      appendError(displayError);
    } finally {
      setPending(false);
      input.focus();
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const message = input.value.trim();
    if (message) {
      void sendMessage(message);
    }
  });

  input.addEventListener("input", resizeInput);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
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

  input.focus();
})();
