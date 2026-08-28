(() => {
  "use strict";

  const form = document.querySelector("#provider-config-form");
  const providerSelect = document.querySelector("#provider-type");
  const apiKeyInput = document.querySelector("#provider-api-key");
  const hostField = document.querySelector("#qweather-host-field");
  const hostInput = document.querySelector("#qweather-api-host");
  const resultMessage = document.querySelector("#config-result");
  const submitButton = document.querySelector("#save-provider-button");

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

  updateConditionalFields();
})();
