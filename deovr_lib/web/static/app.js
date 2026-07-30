(() => {
  const state = {
    page: 1,
    pageSize: window.__PAGE_SIZE__ || 48,
    pages: 1,
    total: 0,
    timer: null,
  };

  const el = {
    q: document.getElementById("q"),
    kind: document.getElementById("kind"),
    library_id: document.getElementById("library_id"),
    sort: document.getElementById("sort"),
    actor: document.getElementById("actor"),
    genre: document.getElementById("genre"),
    studio: document.getElementById("studio"),
    grid: document.getElementById("grid"),
    info: document.getElementById("result-info"),
    pageLabel: document.getElementById("page-label"),
    prev: document.getElementById("prev"),
    next: document.getElementById("next"),
    movies: document.getElementById("stat-movies"),
  };

  const initFilters = window.__INIT_FILTERS__ || {};
  const params = new URLSearchParams(location.search);

  function pendingFilter(key) {
    if (initFilters[key] != null && String(initFilters[key]).length) {
      return String(initFilters[key]);
    }
    return params.get(key) || "";
  }

  const pending = {
    q: pendingFilter("q"),
    kind: pendingFilter("kind"),
    library_id: pendingFilter("library_id"),
    sort: pendingFilter("sort") || "updated",
    actor: pendingFilter("actor"),
    genre: pendingFilter("genre"),
    studio: pendingFilter("studio"),
  };
  if (params.get("page")) state.page = Math.max(1, parseInt(params.get("page"), 10) || 1);
  if (el.q && pending.q) el.q.value = pending.q;
  if (el.kind && pending.kind) el.kind.value = pending.kind;
  if (el.library_id && pending.library_id) el.library_id.value = pending.library_id;
  if (el.sort && pending.sort) el.sort.value = pending.sort;

  function fillSelect(select, items, placeholder, preferred) {
    select.innerHTML = "";
    const opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = placeholder;
    select.appendChild(opt0);
    for (const it of items) {
      const opt = document.createElement("option");
      opt.value = it.name;
      opt.textContent = `${it.name} (${it.cnt})`;
      select.appendChild(opt);
    }
    if (preferred) {
      // 精确匹配；若 facets 列表被截断，仍注入 option 保证筛选生效
      if (![...select.options].some((o) => o.value === preferred)) {
        const opt = document.createElement("option");
        opt.value = preferred;
        opt.textContent = preferred;
        select.appendChild(opt);
      }
      select.value = preferred;
    }
  }

  async function loadFacets() {
    const res = await fetch("/api/facets");
    const data = await res.json();
    fillSelect(el.actor, data.actors, "演员", pending.actor);
    fillSelect(el.genre, data.genres, "类型", pending.genre);
    fillSelect(el.studio, data.studios, "片商", pending.studio);
    if (el.movies && data.stats) el.movies.textContent = data.stats.movies;
  }

  function query() {
    const sp = new URLSearchParams();
    const fields = ["q", "kind", "library_id", "sort", "actor", "genre", "studio"];
    for (const k of fields) {
      const v = (el[k].value || "").trim();
      if (v) sp.set(k, v);
    }
    sp.set("page", String(state.page));
    sp.set("page_size", String(state.pageSize));
    return sp;
  }

  function syncUrl() {
    // 始终留在 /browse，避免跳到 / 被当成首页
    const sp = query();
    history.replaceState(null, "", `/browse?${sp.toString()}`);
  }

  function cardHtml(m) {
    const code = m.code || "";
    const actors = (m.actors || []).slice(0, 2).join(" / ");
    const rev = m.cover_token || m.id;
    const thumb = m.poster_path
      ? `<img class="thumb" loading="lazy" src="/cover/${m.id}?v=${encodeURIComponent(rev)}" alt="" />`
      : `<div class="thumb missing">无封面</div>`;
    return `<a class="card" href="/m/${m.id}">
      ${thumb}
      <div class="body">
        <div class="code">${escapeHtml(code)}</div>
        <div class="title">${escapeHtml(m.title || "")}</div>
        <div class="meta">
          <span>${escapeHtml(actors || m.studio || m.library_name || "")}</span>
          <span class="badge">${(m.kind || "").toUpperCase()}</span>
        </div>
      </div>
    </a>`;
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  async function loadMovies() {
    el.info.textContent = "加载中…";
    el.grid.innerHTML = "";
    syncUrl();
    const res = await fetch(`/api/movies?${query().toString()}`);
    const data = await res.json();
    state.total = data.total;
    state.pages = data.pages;
    state.page = data.page;
    el.info.textContent = `共 ${data.total} 部 · 第 ${data.page}/${data.pages} 页`;
    el.pageLabel.textContent = `${data.page} / ${data.pages}`;
    el.grid.innerHTML =
      data.items.map(cardHtml).join("") || `<p style="color:var(--muted)">无结果</p>`;
    el.prev.disabled = state.page <= 1;
    el.next.disabled = state.page >= state.pages;
  }

  function scheduleLoad() {
    state.page = 1;
    clearTimeout(state.timer);
    state.timer = setTimeout(loadMovies, 220);
  }

  ["kind", "library_id", "sort", "actor", "genre", "studio"].forEach((k) => {
    el[k].addEventListener("change", scheduleLoad);
  });
  el.q.addEventListener("input", scheduleLoad);
  el.prev.addEventListener("click", () => {
    if (state.page > 1) {
      state.page -= 1;
      loadMovies();
    }
  });
  el.next.addEventListener("click", () => {
    if (state.page < state.pages) {
      state.page += 1;
      loadMovies();
    }
  });
  document.getElementById("btn-refresh-facets")?.addEventListener("click", () => {
    loadFacets().then(loadMovies);
  });

  loadFacets().then(loadMovies);
})();
