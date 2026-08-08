(() => {
  const state = {
    page: 1,
    pageSize: window.__PAGE_SIZE__ || 56,
    pages: 1,
    total: 0,
    timer: null,
    facetTimer: null,
  };

  const el = {
    q: document.getElementById("q"),
    kind: document.getElementById("kind"),
    region: document.getElementById("region"),
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
    region: pendingFilter("region"),
    library_id: pendingFilter("library_id"),
    sort: pendingFilter("sort") || "updated",
    actor: pendingFilter("actor"),
    genre: pendingFilter("genre"),
    studio: pendingFilter("studio"),
  };
  // pending 只在首次加载 facets 时用于回填；之后以控件当前值为准，避免改其它筛选时被旧 actor 拉回
  let pendingApplied = false;
  if (params.get("page")) state.page = Math.max(1, parseInt(params.get("page"), 10) || 1);
  if (el.q && pending.q) el.q.value = pending.q;
  if (el.kind && pending.kind) el.kind.value = pending.kind;
  if (el.region && pending.region) el.region.value = pending.region;
  if (el.library_id && pending.library_id) el.library_id.value = pending.library_id;
  if (el.sort && pending.sort) el.sort.value = pending.sort;

  function regionLabel(r) {
    if (r === "jp") return "日本";
    if (r === "western") return "欧美";
    return "";
  }

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

  function facetQuery() {
    const sp = new URLSearchParams();
    // 级联：片种/地区/目录/搜索 + 其它已选 facet 共同缩小选项
    for (const k of ["q", "kind", "region", "library_id", "actor", "genre", "studio"]) {
      const v = (el[k]?.value || "").trim();
      if (v) sp.set(k, v);
    }
    return sp;
  }

  async function loadFacets() {
    const res = await fetch(`/api/facets?${facetQuery().toString()}`);
    const data = await res.json();
    const preferActor = pendingApplied ? el.actor.value : (el.actor.value || pending.actor);
    const preferGenre = pendingApplied ? el.genre.value : (el.genre.value || pending.genre);
    const preferStudio = pendingApplied ? el.studio.value : (el.studio.value || pending.studio);
    fillSelect(el.actor, data.actors, "演员", preferActor);
    fillSelect(el.genre, data.genres, "类型", preferGenre);
    fillSelect(el.studio, data.studios, "片商", preferStudio);
    pendingApplied = true;
    if (el.movies && data.stats) el.movies.textContent = data.stats.movies;
  }

  function query() {
    const sp = new URLSearchParams();
    const fields = ["q", "kind", "region", "library_id", "sort", "actor", "genre", "studio"];
    for (const k of fields) {
      const v = (el[k]?.value || "").trim();
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
    const region = regionLabel(m.region);
    const badges = [(m.kind || "").toUpperCase(), region].filter(Boolean).join(" · ");
    const thumb = m.poster_path
      ? `<img class="thumb" loading="lazy" src="/cover/${m.id}?v=${encodeURIComponent(rev)}" alt="" />`
      : `<div class="thumb missing">无封面</div>`;
    return `<a class="card" href="/m/${m.id}">
      <div class="thumb-wrap">${thumb}</div>
      <div class="body">
        <div class="code">${escapeHtml(code)}</div>
        <div class="title">${escapeHtml(m.title || "")}</div>
        <div class="meta">
          <span>${escapeHtml(actors || m.studio || m.library_name || "")}</span>
          <span class="badge">${escapeHtml(badges)}</span>
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

  function scheduleFacetsAndLoad() {
    state.page = 1;
    clearTimeout(state.timer);
    clearTimeout(state.facetTimer);
    state.facetTimer = setTimeout(() => {
      loadFacets().then(loadMovies);
    }, 220);
  }

  // 片种/地区/目录/搜索变化 → 重载级联 facets + 列表
  ["kind", "region", "library_id"].forEach((k) => {
    el[k]?.addEventListener("change", scheduleFacetsAndLoad);
  });
  // 演员/类型/片商互相关联数量，也重载 facets
  ["actor", "genre", "studio"].forEach((k) => {
    el[k]?.addEventListener("change", scheduleFacetsAndLoad);
  });
  el.sort?.addEventListener("change", scheduleLoad);
  el.q?.addEventListener("input", scheduleFacetsAndLoad);
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
