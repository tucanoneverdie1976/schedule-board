const state = {
  items: [],
};

const SCHEDULE_REFRESH_MS = 5000;
const NEWS_REFRESH_MS = 60000;
const MARKET_REFRESH_MS = 60000;

const els = {
  apiStatus: document.querySelector("#apiStatus"),
  statusText: document.querySelector("#statusText"),
  scheduleList: document.querySelector("#scheduleList"),
  template: document.querySelector("#scheduleTemplate"),
  totalCount: document.querySelector("#totalCount"),
  openCount: document.querySelector("#openCount"),
  boardTitle: document.querySelector("#boardTitle"),
  todayLabel: document.querySelector("#todayLabel"),
  refreshButton: document.querySelector("#refreshButton"),
  newsList: document.querySelector("#newsList"),
  newsTemplate: document.querySelector("#newsTemplate"),
  newsUpdatedText: document.querySelector("#newsUpdatedText"),
  marketList: document.querySelector("#marketList"),
  marketTemplate: document.querySelector("#marketTemplate"),
  marketUpdatedText: document.querySelector("#marketUpdatedText"),
};

function formatDateLabel(value) {
  const date = new Date(`${value}T00:00:00`);
  return new Intl.DateTimeFormat("ko-KR", {
    month: "long",
    day: "numeric",
    weekday: "short",
  }).format(date);
}

function formatNewsTime(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("ko-KR", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
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
    const payload = await request("/api/schedules?range=all");
    state.items = payload.items || [];
    render();
    setStatus(true, "연결됨");
  } catch (error) {
    setStatus(false, error.message);
  }
}

async function loadNews() {
  if (!els.newsList) {
    return;
  }
  try {
    const payload = await request("/api/news");
    renderNews(payload.items || [], payload.updated_at || "");
  } catch (error) {
    els.newsList.innerHTML = "";
    const empty = document.createElement("div");
    empty.className = "empty-state news-empty";
    empty.textContent = "뉴스를 불러오지 못했습니다.";
    els.newsList.append(empty);
    els.newsUpdatedText.textContent = "연결 실패";
  }
}

async function loadMarkets() {
  if (!els.marketList) {
    return;
  }
  try {
    const payload = await request("/api/markets");
    renderMarkets(payload.items || [], payload.updated_at || "", payload.error || "");
  } catch (error) {
    els.marketList.innerHTML = "";
    const empty = document.createElement("div");
    empty.className = "empty-state market-empty";
    empty.textContent = "시장 정보를 불러오지 못했습니다.";
    els.marketList.append(empty);
    els.marketUpdatedText.textContent = "연결 실패";
  }
}

function render() {
  els.scheduleList.innerHTML = "";
  els.boardTitle.textContent = "전체 일정";
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
    card.querySelector(".delete-button").addEventListener("click", () => deleteSchedule(item.id));
    els.scheduleList.append(card);
  }
}

function renderNews(items, updatedAt) {
  els.newsList.innerHTML = "";
  els.newsUpdatedText.textContent = updatedAt ? `${formatNewsTime(updatedAt)} 갱신` : "대기 중";

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state news-empty";
    empty.textContent = "표시할 뉴스가 없습니다.";
    els.newsList.append(empty);
    return;
  }

  for (const item of items.slice(0, 2)) {
    const card = els.newsTemplate.content.firstElementChild.cloneNode(true);
    const title = card.querySelector(".news-title");
    title.textContent = item.title || "뉴스";
    title.href = item.link || "#";
    const metaParts = [item.source, formatNewsTime(item.published_at)].filter(Boolean);
    card.querySelector(".news-meta").textContent = metaParts.join(" · ");
    els.newsList.append(card);
  }
}

function renderMarkets(items, updatedAt, errorText) {
  els.marketList.innerHTML = "";
  els.marketUpdatedText.textContent = updatedAt ? `${formatNewsTime(updatedAt)} 갱신` : "대기 중";
  els.marketUpdatedText.title = errorText || "";

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state market-empty";
    empty.textContent = "표시할 시장 정보가 없습니다.";
    els.marketList.append(empty);
    return;
  }

  for (const item of items) {
    const card = els.marketTemplate.content.firstElementChild.cloneNode(true);
    const direction = item.direction || "flat";
    card.classList.add(direction);
    card.querySelector(".market-name").textContent = item.name || item.code || "시장";
    card.querySelector(".market-status").textContent = [item.status, item.delay].filter(Boolean).join(" · ");
    card.querySelector(".market-value").textContent = item.value || "-";
    card.querySelector(".market-unit").textContent = item.unit || "";

    const changeRate = item.change_rate ? `${item.change_rate}%` : "";
    card.querySelector(".market-change").textContent = [item.change, changeRate].filter(Boolean).join(" · ");

    const metaParts = [item.source, formatNewsTime(item.updated_at)].filter(Boolean);
    card.querySelector(".market-meta").textContent = metaParts.join(" · ");
    els.marketList.append(card);
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

els.refreshButton.addEventListener("click", loadSchedules);

loadSchedules();
loadNews();
loadMarkets();
setInterval(loadSchedules, SCHEDULE_REFRESH_MS);
setInterval(loadNews, NEWS_REFRESH_MS);
setInterval(loadMarkets, MARKET_REFRESH_MS);
