const state = {
  items: [],
};

const SCHEDULE_REFRESH_MS = 5000;
const NEWS_REFRESH_MS = 60000;
const MARKET_REFRESH_MS = 60000;
const ART_REFRESH_MS = 300000;
const SCHEDULE_SCROLL_PX_PER_SECOND = 24;
const ARTWORKS = [
  {
    title: "Water Lilies (Agapanthus)",
    artist: "Claude Monet",
    url: "https://openaccess-cdn.clevelandart.org/1960.81/1960.81_web.jpg",
  },
  {
    title: "Gardener's House at Antibes",
    artist: "Claude Monet",
    url: "https://openaccess-cdn.clevelandart.org/1916.1044/1916.1044_web.jpg",
  },
  {
    title: "Vale of Kashmir",
    artist: "Robert S. Duncanson",
    url: "https://openaccess-cdn.clevelandart.org/2014.12/2014.12_web.jpg",
  },
  {
    title: "Rocky, Wooded Landscape",
    artist: "Thomas Gainsborough",
    url: "https://openaccess-cdn.clevelandart.org/1984.59/1984.59_web.jpg",
  },
  {
    title: "Prater Landscape",
    artist: "Ferdinand Georg Waldmuller",
    url: "https://openaccess-cdn.clevelandart.org/1983.155/1983.155_web.jpg",
  },
  {
    title: "Landscape with Large Trees",
    artist: "Gustave Courbet",
    url: "https://openaccess-cdn.clevelandart.org/1976.18/1976.18_web.jpg",
  },
  {
    title: "The Seine at Bas-Meudon",
    artist: "Johan Barthold Jongkind",
    url: "https://openaccess-cdn.clevelandart.org/1993.236/1993.236_web.jpg",
  },
  {
    title: "Landscape",
    artist: "Soami",
    url: "https://openaccess-cdn.clevelandart.org/1963.262/1963.262_web.jpg",
  },
];

let activeArtIndex = -1;
const scheduleScroll = {
  cycleHeight: 0,
  hasRendered: false,
  lastFrameAt: 0,
  offset: 0,
  signature: "",
};

const els = {
  apiStatus: document.querySelector("#apiStatus"),
  statusText: document.querySelector("#statusText"),
  pageTitle: document.querySelector("#pageTitle"),
  scheduleList: document.querySelector("#scheduleList"),
  template: document.querySelector("#scheduleTemplate"),
  newsList: document.querySelector("#newsList"),
  newsTemplate: document.querySelector("#newsTemplate"),
  newsUpdatedText: document.querySelector("#newsUpdatedText"),
  marketList: document.querySelector("#marketList"),
  marketTemplate: document.querySelector("#marketTemplate"),
  marketUpdatedText: document.querySelector("#marketUpdatedText"),
  artImage: document.querySelector("#artImage"),
  artTitle: document.querySelector("#artTitle"),
  artArtist: document.querySelector("#artArtist"),
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

function formatTodayTitle() {
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(new Date());
}

function renderTodayTitle() {
  const title = formatTodayTitle();
  if (els.pageTitle) {
    els.pageTitle.textContent = title;
  }
  document.title = title;
}

function setStatus(ok, text) {
  els.apiStatus.classList.toggle("ok", ok);
  els.statusText.textContent = text;
}

function getScheduleSignature(items) {
  return items
    .map((item, index) => [
      item.id || index,
      item.date || "",
      item.time || "",
      item.title || "",
      item.done ? "1" : "0",
    ].join(":"))
    .join("|");
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
    const items = payload.items || [];
    const nextSignature = getScheduleSignature(items);
    const shouldRender = !scheduleScroll.hasRendered || nextSignature !== scheduleScroll.signature;
    state.items = items;
    if (shouldRender) {
      render();
    }
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

function createScheduleCard(item, index) {
  const card = els.template.content.firstElementChild.cloneNode(true);
  card.classList.toggle("done", item.done);
  card.querySelector(".schedule-number").textContent = index + 1;
  card.querySelector("h3").textContent = item.title;
  card.querySelector(".card-time").textContent = `${formatDateLabel(item.date)}${item.time ? ` · ${item.time}` : ""}`;

  const notes = card.querySelector(".card-notes");
  notes.textContent = item.notes || "";
  notes.hidden = !notes.textContent;

  return card;
}

function createScheduleCycle(items, hidden = false) {
  const cycle = document.createElement("div");
  cycle.className = "schedule-cycle";
  if (hidden) {
    cycle.setAttribute("aria-hidden", "true");
  }

  items.forEach((item, index) => {
    cycle.append(createScheduleCard(item, index));
  });

  return cycle;
}

function render() {
  scheduleScroll.hasRendered = true;
  const previousOffset = scheduleScroll.offset;
  const nextSignature = getScheduleSignature(state.items);
  const scheduleChanged = nextSignature !== scheduleScroll.signature;

  renderTodayTitle();
  els.scheduleList.innerHTML = "";

  if (!state.items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "표시할 일정이 없습니다.";
    els.scheduleList.append(empty);
    requestAnimationFrame(() => syncScheduleScroll(true, 0, nextSignature));
    return;
  }

  const track = document.createElement("div");
  track.className = "schedule-track";
  track.append(createScheduleCycle(state.items));
  track.append(createScheduleCycle(state.items, true));

  els.scheduleList.append(track);

  requestAnimationFrame(() => {
    syncScheduleScroll(scheduleChanged, previousOffset, nextSignature);
  });
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

function refreshArt() {
  if (!els.artImage) {
    return;
  }

  let nextIndex = activeArtIndex;
  while (nextIndex === activeArtIndex && ARTWORKS.length > 1) {
    nextIndex = Math.floor(Math.random() * ARTWORKS.length);
  }
  activeArtIndex = nextIndex;

  const artwork = ARTWORKS[activeArtIndex];
  els.artImage.classList.add("is-loading");
  els.artImage.src = artwork.url;
  if (els.artTitle) {
    els.artTitle.textContent = artwork.title;
  }
  if (els.artArtist) {
    els.artArtist.textContent = artwork.artist;
  }
}

function getScheduleTrack() {
  return els.scheduleList.querySelector(".schedule-track");
}

function getScheduleCycleHeight(track) {
  if (!track) {
    return 0;
  }
  const cycles = track.querySelectorAll(".schedule-cycle");
  if (cycles.length < 2) {
    return cycles[0]?.scrollHeight || 0;
  }
  const firstRect = cycles[0].getBoundingClientRect();
  const secondRect = cycles[1].getBoundingClientRect();
  return Math.max(0, secondRect.top - firstRect.top);
}

function applyScheduleOffset(track) {
  if (!track) {
    return;
  }
  track.style.transform = `translate3d(0, ${-scheduleScroll.offset}px, 0)`;
}

function syncScheduleScroll(reset, previousOffset, signature) {
  const track = getScheduleTrack();
  const cycleHeight = getScheduleCycleHeight(track);
  const isScrollable = cycleHeight > els.scheduleList.clientHeight + 2;

  els.scheduleList.classList.toggle("is-scrollable", isScrollable);
  scheduleScroll.cycleHeight = cycleHeight;
  scheduleScroll.signature = signature;

  if (!isScrollable) {
    scheduleScroll.offset = 0;
    applyScheduleOffset(track);
    return;
  }

  if (reset) {
    scheduleScroll.offset = 0;
    applyScheduleOffset(track);
    return;
  }

  scheduleScroll.offset = cycleHeight ? previousOffset % cycleHeight : 0;
  applyScheduleOffset(track);
}

function animateScheduleScroll(frameAt) {
  const track = getScheduleTrack();
  const cycleHeight = getScheduleCycleHeight(track);

  if (cycleHeight > els.scheduleList.clientHeight + 2) {
    els.scheduleList.classList.add("is-scrollable");
    scheduleScroll.cycleHeight = cycleHeight;

    if (!scheduleScroll.lastFrameAt) {
      scheduleScroll.lastFrameAt = frameAt;
    }

    const deltaMs = Math.min(80, frameAt - scheduleScroll.lastFrameAt);
    scheduleScroll.offset += SCHEDULE_SCROLL_PX_PER_SECOND * (deltaMs / 1000);
    if (scheduleScroll.offset >= cycleHeight) {
      scheduleScroll.offset %= cycleHeight;
    }
    applyScheduleOffset(track);
  } else {
    els.scheduleList.classList.remove("is-scrollable");
    scheduleScroll.offset = 0;
    applyScheduleOffset(track);
  }

  scheduleScroll.lastFrameAt = frameAt;
  requestAnimationFrame(animateScheduleScroll);
}

if (els.artImage) {
  els.artImage.addEventListener("load", () => {
    els.artImage.classList.remove("is-loading", "is-hidden");
  });
  els.artImage.addEventListener("error", () => {
    els.artImage.classList.add("is-hidden");
    els.artImage.classList.remove("is-loading");
  });
}

renderTodayTitle();
loadSchedules();
loadNews();
loadMarkets();
refreshArt();
requestAnimationFrame(animateScheduleScroll);
setInterval(renderTodayTitle, 60000);
setInterval(loadSchedules, SCHEDULE_REFRESH_MS);
setInterval(loadNews, NEWS_REFRESH_MS);
setInterval(loadMarkets, MARKET_REFRESH_MS);
setInterval(refreshArt, ART_REFRESH_MS);
