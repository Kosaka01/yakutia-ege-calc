const formConfig = [
  { id: "form-full", key: "fullTime", label: "Очная" },
  { id: "form-part", key: "partTime", label: "Очно-заочная" },
  { id: "form-extramural", key: "extramural", label: "Заочная" },
];

const elements = {
  scoresGrid: document.getElementById("scores-grid"),
  includeAdditional: document.getElementById("include-additional"),
  citySelect: document.getElementById("city-select"),
  results: document.getElementById("results"),
  emptyState: document.getElementById("empty-state"),
  totalPrograms: document.getElementById("total-programs"),
  matchedPrograms: document.getElementById("matched-programs"),
  resultsSummary: document.getElementById("results-summary"),
  priceValue: document.getElementById("price-value"),
  sendEmail: document.getElementById("send-email"),
  emailField: document.getElementById("email-field"),
  emailInput: document.getElementById("email-input"),
  payButton: document.getElementById("pay-button"),
  paymentStatus: document.getElementById("payment-status"),
  paymentPanel: document.getElementById("payment-panel"),
};

let totalPrograms = 0;
let pollTimer = null;

function formatRequirements(requirements) {
  if (!requirements || !requirements.groups || !requirements.groups.length) {
    return ["Нет данных о вступительных испытаниях."];
  }

  return requirements.groups.map((group) =>
    group.options
      .map((option) => {
        if (option.minScore !== null) {
          return `${option.subject} - ${option.minScore} б.`;
        }
        return option.subject;
      })
      .join(" или ")
  );
}

function getScores() {
  const scores = {};
  const inputs = elements.scoresGrid.querySelectorAll("input[data-subject]");
  inputs.forEach((input) => {
    const subject = input.dataset.subject;
    const value = input.value.trim();
    if (value === "") {
      scores[subject] = null;
      return;
    }
    const numeric = Number.parseInt(value, 10);
    if (Number.isNaN(numeric)) {
      scores[subject] = null;
      return;
    }
    scores[subject] = Math.min(Math.max(numeric, 0), 100);
  });
  return scores;
}

function hasAnyScore(scores) {
  return Object.values(scores).some((value) => typeof value === "number" && value > 0);
}

function getSelectedForms() {
  return formConfig
    .filter((form) => {
      const checkbox = document.getElementById(form.id);
      return checkbox && checkbox.checked;
    })
    .map((form) => form.key);
}

function formatSeats(program) {
  const rows = [];
  for (const form of formConfig) {
    const seats = program.seats[form.key];
    if (!seats) continue;
    const total = (seats.budget || 0) + (seats.paid || 0);
    if (total === 0) continue;
    rows.push({
      label: form.label,
      budget: seats.budget || 0,
      paid: seats.paid || 0,
    });
  }
  return rows;
}

function renderResults(list) {
  elements.results.innerHTML = "";
  const byUniversity = new Map();
  list.forEach((program) => {
    const key = program.university || "Неизвестный вуз";
    if (!byUniversity.has(key)) {
      byUniversity.set(key, []);
    }
    byUniversity.get(key).push(program);
  });

  const createProgramCard = (program, index) => {
    const card = document.createElement("article");
    card.className = "card";
    card.style.setProperty("--delay", `${index * 0.03}s`);

    const title = document.createElement("h3");
    const code = program.programCode ? `${program.programCode} - ` : "";
    title.textContent = `${code}${program.programName || "Без названия"}`;

    const meta = document.createElement("div");
    meta.className = "meta";
    const metaParts = [program.location, program.unitName || program.unitCode].filter(Boolean);
    meta.textContent = metaParts.join(" • ");

    const badges = document.createElement("div");
    badges.className = "badges";
    if (program.requirements && program.requirements.hasAdditional) {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = "Требуются доп. испытания";
      badges.appendChild(badge);
    }

    const requirements = document.createElement("div");
    requirements.className = "requirements";
    const reqLines = formatRequirements(program.requirements);
    reqLines.forEach((line) => {
      const row = document.createElement("div");
      row.textContent = line;
      requirements.appendChild(row);
    });

    const seats = document.createElement("div");
    seats.className = "seats";
    const seatRows = formatSeats(program);
    if (!seatRows.length) {
      const row = document.createElement("div");
      row.className = "seat-row";
      row.textContent = "Нет мест";
      seats.appendChild(row);
    } else {
      seatRows.forEach((rowData) => {
        const row = document.createElement("div");
        row.className = "seat-row";
        row.innerHTML = `${rowData.label} <span>Бюджет ${rowData.budget}, Платно ${rowData.paid}</span>`;
        seats.appendChild(row);
      });
    }

    card.appendChild(title);
    card.appendChild(meta);
    if (badges.children.length) {
      card.appendChild(badges);
    }
    card.appendChild(requirements);
    card.appendChild(seats);

    return card;
  };

  const formatUnitLabel = (program) => {
    if (program.unitCode && program.unitName) {
      return `${program.unitCode} - ${program.unitName}`;
    }
    return program.unitName || program.unitCode || "УчП не указано";
  };

  let cardIndex = 0;
  byUniversity.forEach((uniPrograms, university) => {
    const uniDetails = document.createElement("details");
    uniDetails.className = "group uni-group";

    const uniSummary = document.createElement("summary");
    uniSummary.textContent = `${university} · программ: ${uniPrograms.length}`;
    uniDetails.appendChild(uniSummary);

    const uniBody = document.createElement("div");
    uniBody.className = "uni-body";

    const units = new Map();
    uniPrograms.forEach((program) => {
      const key = program.unitCode || program.unitName || "УчП не указано";
      if (!units.has(key)) {
        units.set(key, []);
      }
      units.get(key).push(program);
    });

    if (units.size > 1) {
      units.forEach((unitPrograms) => {
        const unitDetails = document.createElement("details");
        unitDetails.className = "group unit-group";

        const unitSummary = document.createElement("summary");
        unitSummary.textContent = `${formatUnitLabel(unitPrograms[0])} · программ: ${unitPrograms.length}`;
        unitDetails.appendChild(unitSummary);

        const unitBody = document.createElement("div");
        unitBody.className = "unit-body";
        unitPrograms.forEach((program) => {
          unitBody.appendChild(createProgramCard(program, cardIndex++));
        });

        unitDetails.appendChild(unitBody);
        uniBody.appendChild(unitDetails);
      });
    } else {
      uniPrograms.forEach((program) => {
        uniBody.appendChild(createProgramCard(program, cardIndex++));
      });
    }

    uniDetails.appendChild(uniBody);
    elements.results.appendChild(uniDetails);
  });
}

function updateCityOptions(cities) {
  elements.citySelect.innerHTML = "";

  const allOption = document.createElement("option");
  allOption.value = "all";
  allOption.textContent = "Все города";
  elements.citySelect.appendChild(allOption);

  cities.forEach((city) => {
    const option = document.createElement("option");
    option.value = city;
    option.textContent = city;
    elements.citySelect.appendChild(option);
  });
}

function updateStats(total, matched) {
  elements.totalPrograms.textContent = total;
  elements.matchedPrograms.textContent = matched;
}

function setPaymentStatus(message, isError = false) {
  elements.paymentStatus.textContent = message;
  elements.paymentStatus.style.color = isError ? "#b54c28" : "";
}

function clearResults() {
  elements.results.innerHTML = "";
  elements.emptyState.hidden = true;
  elements.resultsSummary.textContent = "Введите баллы и оплатите, чтобы увидеть доступные программы.";
  updateStats(totalPrograms, 0);
}

function applyResults(results) {
  updateStats(totalPrograms, results.length);
  elements.resultsSummary.textContent = `Найдено программ: ${results.length}`;
  elements.emptyState.hidden = results.length !== 0;
  renderResults(results);
}

function lockInputs(lock) {
  const inputs = elements.scoresGrid.querySelectorAll("input[data-subject]");
  inputs.forEach((input) => (input.disabled = lock));
  elements.includeAdditional.disabled = lock;
  elements.citySelect.disabled = lock;
  formConfig.forEach((form) => {
    const checkbox = document.getElementById(form.id);
    if (checkbox) checkbox.disabled = lock;
  });
  elements.sendEmail.disabled = lock;
  elements.emailInput.disabled = lock;
  elements.payButton.disabled = lock;
}

function updatePayButtonState() {
  const scores = getScores();
  const selectedForms = getSelectedForms();
  elements.payButton.disabled = !(hasAnyScore(scores) && selectedForms.length);
}

function buildPayload() {
  return {
    scores: getScores(),
    filters: {
      includeAdditional: elements.includeAdditional.checked,
      city: elements.citySelect.value,
      forms: getSelectedForms(),
    },
    sendEmail: elements.sendEmail.checked,
    email: elements.emailInput.value.trim(),
  };
}

function isEmailValid(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

async function createPayment() {
  const payload = buildPayload();
  if (!hasAnyScore(payload.scores)) {
    setPaymentStatus("Введите хотя бы один предмет.", true);
    return;
  }
  if (!payload.filters.forms.length) {
    setPaymentStatus("Выберите хотя бы одну форму обучения.", true);
    return;
  }
  if (payload.sendEmail && !payload.email) {
    setPaymentStatus("Укажите e-mail для отправки результата.", true);
    return;
  }
  if (payload.sendEmail && !isEmailValid(payload.email)) {
    setPaymentStatus("Проверьте корректность e-mail.", true);
    return;
  }

  setPaymentStatus("Создаем платеж...");
  elements.payButton.disabled = true;

  try {
    const response = await fetch("/api/create-payment", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Ошибка создания платежа");
    }
    sessionStorage.setItem("order_id", data.orderId);
    window.location.href = data.confirmationUrl;
  } catch (error) {
    setPaymentStatus(error.message || "Не удалось создать платеж.", true);
    elements.payButton.disabled = false;
  }
}

async function fetchPaymentStatus(orderId) {
  const response = await fetch(`/api/payment-status?order_id=${encodeURIComponent(orderId)}`);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Ошибка проверки платежа");
  }
  return data;
}

async function pollPayment(orderId) {
  if (pollTimer) {
    clearTimeout(pollTimer);
  }

  try {
    const status = await fetchPaymentStatus(orderId);
    if (status.paid) {
      setPaymentStatus("Оплата подтверждена. Загружаем результаты...");
      elements.paymentPanel.hidden = true;
      lockInputs(true);
      if (status.results) {
        applyResults(status.results);
      }
      sessionStorage.removeItem("order_id");
      if (window.location.search.includes("order_id")) {
        window.history.replaceState({}, document.title, window.location.pathname);
      }
      return;
    }

    if (status.status === "canceled") {
      setPaymentStatus("Платеж отменен. Попробуйте снова.", true);
      elements.payButton.disabled = false;
      return;
    }

    setPaymentStatus("Ожидаем подтверждение оплаты...");
    pollTimer = setTimeout(() => pollPayment(orderId), 3000);
  } catch (error) {
    setPaymentStatus(error.message || "Не удалось проверить оплату.", true);
  }
}

async function init() {
  try {
    const response = await fetch("/api/metadata");
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const metadata = await response.json();
    totalPrograms = metadata.totalPrograms || 0;
    updateStats(totalPrograms, 0);
    updateCityOptions(metadata.cities || []);
    elements.priceValue.textContent = metadata.priceRub || "—";
  } catch (error) {
    updateStats(0, 0);
    elements.resultsSummary.textContent =
      "Не удалось загрузить данные. Проверьте запуск бэкенда.";
    elements.payButton.disabled = true;
    console.error(error);
  }

  clearResults();

  const inputs = elements.scoresGrid.querySelectorAll("input[data-subject]");
  inputs.forEach((input) => input.addEventListener("input", updatePayButtonState));
  elements.includeAdditional.addEventListener("change", updatePayButtonState);
  elements.citySelect.addEventListener("change", updatePayButtonState);
  formConfig.forEach((form) => {
    const checkbox = document.getElementById(form.id);
    if (checkbox) checkbox.addEventListener("change", updatePayButtonState);
  });

  elements.sendEmail.addEventListener("change", () => {
    elements.emailField.hidden = !elements.sendEmail.checked;
  });

  elements.payButton.addEventListener("click", (event) => {
    event.preventDefault();
    createPayment();
  });

  const params = new URLSearchParams(window.location.search);
  const orderId = params.get("order_id") || sessionStorage.getItem("order_id");
  if (orderId) {
    setPaymentStatus("Проверяем оплату...");
    pollPayment(orderId);
  } else {
    updatePayButtonState();
  }
}

init();
