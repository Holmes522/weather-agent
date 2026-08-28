(() => {
  "use strict";

  const form = document.querySelector("#provider-config-form");
  const providerSelect = document.querySelector("#provider-type");
  const apiKeyInput = document.querySelector("#provider-api-key");
  const hostField = document.querySelector("#qweather-host-field");
  const hostInput = document.querySelector("#qweather-api-host");
  const resultMessage = document.querySelector("#config-result");
  const submitButton = document.querySelector("#save-provider-button");
  const llmForm = document.querySelector("#llm-config-form");
  const llmProvider = document.querySelector("#llm-provider");
  const llmModel = document.querySelector("#llm-model");
  const llmApiKey = document.querySelector("#llm-api-key");
  const llmBaseUrlField = document.querySelector("#llm-base-url-field");
  const llmBaseUrl = document.querySelector("#llm-base-url");
  const llmResult = document.querySelector("#llm-config-result");
  const llmSubmit = document.querySelector("#save-llm-button");
  const llmStatus = document.querySelector("#llm-status");

  function updateConditionalFields() {
    const needsHost = providerSelect.value === "qweather";
    hostField.hidden = !needsHost;
    hostInput.required = needsHost;
    if (!needsHost) {
      hostInput.value = "";
    }
  }

  function setPending(pending) {
    providerSelect.disabled = pending;
    apiKeyInput.disabled = pending;
    hostInput.disabled = pending;
    submitButton.disabled = pending;
    submitButton.textContent = pending ? "正在保存…" : "保存到当前进程";
  }

  function showMessage(message, state) {
    resultMessage.textContent = message;
    resultMessage.dataset.state = state;
  }

  function markProviderConfigured(providerId) {
    const items = document.querySelectorAll("[data-provider-status]");
    items.forEach((item) => {
      if (item.dataset.providerStatus === providerId) {
        item.classList.add("is-configured");
        const state = item.querySelector(".provider-state");
        if (state) {
          state.textContent = "已配置";
        }
      }
    });
  }

  providerSelect.addEventListener("change", updateConditionalFields);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    showMessage("", "");
    setPending(true);

    const payload = {
      provider: providerSelect.value,
      api_key: apiKeyInput.value.trim(),
    };
    if (providerSelect.value === "qweather") {
      payload.api_host = hostInput.value.trim();
    }

    try {
      const response = await fetch("/api/providers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok || !body) {
        throw new Error(
          body?.error?.message || "配置保存失败，请检查输入后重试。",
        );
      }

      markProviderConfigured(body.provider.id);
      apiKeyInput.value = "";
      showMessage(`${body.provider.name} 已加入数据源，返回聊天页即可选择。`, "success");
    } catch (error) {
      const safeMessage =
        error instanceof Error &&
        error.message !== "Failed to fetch" &&
        error.message !== "Load failed"
          ? error.message
          : "无法连接到本地服务，请确认 Flask 正在运行。";
      showMessage(safeMessage, "error");
    } finally {
      setPending(false);
      apiKeyInput.focus();
    }
  });

  function updateLlmFields() {
    const option = llmProvider.selectedOptions[0];
    const isCustom = llmProvider.value === "custom";
    const requiresKey = option?.dataset.requiresKey !== "false";
    llmBaseUrlField.hidden = !isCustom;
    llmBaseUrl.required = isCustom;
    llmApiKey.required = requiresKey;
    if (!isCustom) {
      llmBaseUrl.value = "";
    }

    const placeholders = {
      deepseek: "例如 deepseek-v4-flash",
      openrouter: "例如 openai/gpt-4.1-mini",
      ollama: "例如 qwen3:8b（需先在本机拉取）",
    };
    llmModel.placeholder = placeholders[llmProvider.value] || "输入服务控制台中的模型 ID";
  }

  function setLlmPending(pending) {
    llmProvider.disabled = pending;
    llmModel.disabled = pending;
    llmApiKey.disabled = pending;
    llmBaseUrl.disabled = pending;
    llmSubmit.disabled = pending;
    llmSubmit.textContent = pending ? "正在保存…" : "保存 AI 模型到当前进程";
  }

  llmProvider.addEventListener("change", updateLlmFields);
  llmForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    llmResult.textContent = "";
    llmResult.dataset.state = "";
    setLlmPending(true);

    const payload = {
      provider: llmProvider.value,
      model: llmModel.value.trim(),
      api_key: llmApiKey.value.trim(),
    };
    if (llmProvider.value === "custom") {
      payload.base_url = llmBaseUrl.value.trim();
    }

    try {
      const response = await fetch("/api/llm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok || !body?.llm) {
        throw new Error(body?.error?.message || "模型配置保存失败，请检查输入。" );
      }

      llmApiKey.value = "";
      llmStatus.textContent = `${body.llm.provider} · ${body.llm.model}`;
      llmStatus.classList.add("is-configured");
      llmResult.textContent = "AI 模型已连接，返回聊天页即可进行通用对话。";
      llmResult.dataset.state = "success";
    } catch (error) {
      const safeMessage =
        error instanceof Error &&
        error.message !== "Failed to fetch" &&
        error.message !== "Load failed"
          ? error.message
          : "无法连接到本地服务，请确认 Flask 正在运行。";
      llmResult.textContent = safeMessage;
      llmResult.dataset.state = "error";
    } finally {
      setLlmPending(false);
      llmModel.focus();
    }
  });

  updateConditionalFields();
  updateLlmFields();
})();
