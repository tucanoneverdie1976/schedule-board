const state = {
  range: "today",
  items: [],
  editingId: null,
};

const AUTO_REFRESH_MS = 30000;

const els = {
  apiStatus: document.querySelector("#apiStatus"),
  statusText: document.querySelector("#statusText"),
  scheduleForm: document.querySelector("#scheduleForm"),
  voiceForm: document.querySelector("#voiceForm"),
  titleInput: document.querySelector("#titleInput"),
  dateInput: document.querySelector("#dateInput"),
  timeInput: document.querySelector("#timeInput"),
  notesInput: document.querySelector("#notesInput"),
  voiceInput: document.querySelector("#voiceInput"),
  scheduleList: document.querySelector("#scheduleList"),
  template: document.querySelector("#scheduleTemplate"),
  totalCount: document.querySelector("#totalCount"),
  openCount: document.querySelector("#openCount"),
  boardTitle: document.querySelector("#boardTitle"),
  todayLabel: document.querySelector("#todayLabel"),
  refreshButton: document.querySelector("#refreshButton"),
  cancelEdit: document.querySelector("#cancelEdit"),
  formTitle: document.querySelector("#formTitle"),
  saveButton: document.querySelector("#saveButton"),
};

const rangeTitles = {
  today: "오늘 일정",
  week: "이번 주 일정",
  all: "전체 일정",
};

function todayIso() {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}

function formatDateLabel(value) {
  const date = new Date(`${value}T00:00:00`);
  return new Intl.DateTimeFormat("ko-KR", {
    month: "long",
    day: "numeric",
    weekday: "short",
  }).format(date);
}

function setStatus(ok, text) {
  els.apiStatus.classList.toggle("ok", ok);
  els.statusText.textContent = text;
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "요청 처리 실패");
  }
  return payload;
}

async function loadSchedules() {
  try {
    const payload = await request(`/api/schedules?range=${state.range}`);
    state.items = payload.items || [];
    render();
    setStatus(true, "연결됨");
  } catch (error) {
    setStatus(false, error.message);
  }
}

function render() {
  els.scheduleList.innerHTML = "";
  els.boardTitle.textContent = rangeTitles[state.range];
  els.todayLabel.textContent = new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(new Date());

  els.totalCount.textContent = state.items.length;
  els.openCount.textContent = state.items.filter((item) => !item.done).length;

  if (!state.items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "표시할 일정이 없습니다.";
    els.scheduleList.append(empty);
    return;
  }

  for (const item of state.items) {
    const card = els.template.content.firstElementChild.cloneNode(true);
    card.classList.toggle("done", item.done);
    card.querySelector("h3").textContent = item.title;
    card.querySelector(".card-time").textContent = `${formatDateLabel(item.date)}${item.time ? ` · ${item.time}` : ""}`;

    const notes = card.querySelector(".card-notes");
    notes.textContent = item.notes || (item.source === "voice" ? "음성으로 추가됨" : "");
    notes.hidden = !notes.textContent;

    card.querySelector(".done-toggle").addEventListener("click", () => updateSchedule(item.id, { ...item, done: !item.done }));
    card.querySelector(".edit-button").addEventListener("click", () => startEdit(item));
    card.querySelector(".delete-button").addEventListener("click", () => deleteSchedule(item.id));
    els.scheduleList.append(card);
  }
}

function scheduleFromForm() {
  return {
    title: els.titleInput.value.trim(),
    date: els.dateInput.value,
    time: els.timeInput.value,
    notes: els.notesInput.value.trim(),
    source: "web",
  };
}

function resetForm() {
  state.editingId = null;
  els.scheduleForm.reset();
  els.dateInput.value = todayIso();
  els.formTitle.textContent = "일정 추가";
  els.saveButton.textContent = "추가";
  els.cancelEdit.classList.add("hidden");
}

function startEdit(item) {
  state.editingId = item.id;
  els.titleInput.value = item.title || "";
  els.dateInput.value = item.date || todayIso();
  els.timeInput.value = item.time || "";
  els.notesInput.value = item.notes || "";
  els.formTitle.textContent = "일정 수정";
  els.saveButton.textContent = "저장";
  els.cancelEdit.classList.remove("hidden");
  els.titleInput.focus();
}

async function saveSchedule(event) {
  event.preventDefault();
  const payload = scheduleFromForm();
  if (!payload.title || !payload.date) {
    return;
  }
  try {
    if (state.editingId) {
      await updateSchedule(state.editingId, payload);
    } else {
      await request("/api/schedules", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    }
    resetForm();
    await loadSchedules();
  } catch (error) {
    setStatus(false, error.message);
  }
}

async function updateSchedule(id, payload) {
  try {
    await request(`/api/schedules/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    await loadSchedules();
  } catch (error) {
    setStatus(false, error.message);
  }
}

async function deleteSchedule(id) {
  try {
    await request(`/api/schedules/${id}`, { method: "DELETE" });
    await loadSchedules();
  } catch (error) {
    setStatus(false, error.message);
  }
}

async function addVoiceCommand(event) {
  event.preventDefault();
  const text = els.voiceInput.value.trim();
  if (!text) {
    return;
  }
  try {
    const result = await request("/api/voice-command", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    els.voiceInput.value = "";
    await loadSchedules();
    if (result.action === "deleted") {
      setStatus(true, "삭제됨");
    } else if (result.action === "added") {
      setStatus(true, "추가됨");
    }
  } catch (error) {
    setStatus(false, error.message);
  }
}

document.querySelectorAll(".filter-button").forEach((button) => {
  button.addEventListener("click", async () => {
    document.querySelectorAll(".filter-button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    state.range = button.dataset.range;
    await loadSchedules();
  });
});

els.scheduleForm.addEventListener("submit", saveSchedule);
els.voiceForm.addEventListener("submit", addVoiceCommand);
els.refreshButton.addEventListener("click", loadSchedules);
els.cancelEdit.addEventListener("click", resetForm);

resetForm();
loadSchedules();
setInterval(loadSchedules, AUTO_REFRESH_MS);
