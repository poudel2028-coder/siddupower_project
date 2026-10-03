const API_BASE = (() => {
  if (window.SIDESTACK_API) return window.SIDESTACK_API;
  const host = location.hostname;
  if (host === "localhost" || host === "127.0.0.1") {
    return location.port === "8000" ? "" : "http://127.0.0.1:8000";
  }
  return "/api";
})();

const store = {
  get token() {
    return localStorage.getItem("sidestack_token");
  },
  set token(v) {
    if (v) localStorage.setItem("sidestack_token", v);
    else localStorage.removeItem("sidestack_token");
  },
};

let me = null;
let pollTimer = null;
let selectedPlayerId = null;
let currentMatchId = null;

const $ = (id) => document.getElementById(id);

function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 2800);
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (store.token) headers.Authorization = `Bearer ${store.token}`;
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.message || "Request failed");
  return data;
}

function showAuth(on) {
  $("view-auth").classList.toggle("hidden", !on);
  $("view-app").classList.toggle("hidden", on);
}

function setPage(name, title) {
  document.querySelectorAll(".page").forEach((p) => p.classList.add("hidden"));
  $(`page-${name}`).classList.remove("hidden");
  $("app-title").textContent = title || name;
  document.querySelectorAll(".tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.page === name);
  });
}

function sportLabel(s) {
  return s === "football" ? "Football" : "Basketball";
}

function renderHome(data) {
  const s = data.stats;
  $("hello").textContent = `Hey, ${data.user.username}`;
  $("page-home").innerHTML = `
    <div class="grid">
      <div class="stats">
        <div class="glass stat"><span>Points / Goals</span><b>${s.points}</b></div>
        <div class="glass stat"><span>Games</span><b>${s.games}</b></div>
        <div class="glass stat"><span>MVPs</span><b>${s.mvp_count}</b></div>
        <div class="glass stat"><span>Fouls</span><b>${s.fouls}</b></div>
      </div>
      <section class="glass card">
        <h3>Your teams</h3>
        <div class="list">
          ${
            data.teams.length
              ? data.teams
                  .map(
                    (t) =>
                      `<div class="item glass"><div class="row"><strong>${t.name}</strong><span class="chip">${sportLabel(
                        t.sport_type
                      )}</span></div><p class="muted">Code ${t.join_code} · ${t.members.length} players</p></div>`
                  )
                  .join("")
              : `<p class="muted">No teams yet. Create or join one from the Teams tab.</p>`
          }
        </div>
      </section>
      <section class="glass card">
        <h3>Recent games</h3>
        <div class="list">
          ${
            data.recent_matches.length
              ? data.recent_matches
                  .map(
                    (m) =>
                      `<button class="item glass" data-open-match="${m.id}"><div class="row"><strong>${m.team1.name} ${m.team1_score} – ${m.team2_score} ${m.team2.name}</strong><span class="chip">${m.status}</span></div></button>`
                  )
                  .join("")
              : `<p class="muted">No games yet. Challenge someone.</p>`
          }
        </div>
      </section>
    </div>`;
}

async function loadHome() {
  const data = await api("/me");
  me = data.user;
  renderHome(data);
}

async function loadFriends() {
  const friends = await api("/friends");
  $("page-friends").innerHTML = `
    <div class="grid">
      <form id="form-search" class="glass card stack">
        <label>Find a player<input name="q" placeholder="Search username" required /></label>
        <button class="btn primary" type="submit">Search</button>
      </form>
      <div id="search-results" class="list"></div>
      <section class="glass card">
        <h3>Squad</h3>
        <div class="list">
          ${
            friends.friends.length
              ? friends.friends
                  .map(
                    (f) =>
                      `<button class="item glass" data-profile="${f.id}"><div class="row"><strong>${f.username}</strong><span class="chip">${sportLabel(
                        f.primary_sport
                      )}</span></div></button>`
                  )
                  .join("")
              : `<p class="muted">No friends yet. Search above.</p>`
          }
        </div>
      </section>
    </div>`;
  $("form-search").addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = new FormData(e.target).get("q");
    const res = await api(`/users/search?q=${encodeURIComponent(q)}`);
    $("search-results").innerHTML = res.users
      .map(
        (u) =>
          `<div class="item glass row"><div><strong>${u.username}</strong><div class="muted">${sportLabel(
            u.primary_sport
          )}</div></div>${
            u.is_friend
              ? `<button class="btn ghost" data-profile="${u.id}">Profile</button>`
              : `<button class="btn primary" data-add="${u.username}">Add</button>`
          }</div>`
      )
      .join("");
  });
}

async function loadTeams() {
  const data = await api("/teams");
  $("page-teams").innerHTML = `
    <div class="grid">
      <form id="form-create-team" class="glass card stack">
        <h3>Create team</h3>
        <label>Name<input name="name" required minlength="2" /></label>
        <label>Sport
          <select name="sport_type">
            <option value="basketball">Basketball</option>
            <option value="football">Football</option>
          </select>
        </label>
        <button class="btn primary" type="submit">Generate join code</button>
      </form>
      <form id="form-join-team" class="glass card stack">
        <h3>Join team</h3>
        <label>4-character code<input name="join_code" maxlength="4" minlength="4" required style="text-transform:uppercase" /></label>
        <button class="btn ghost" type="submit">Join roster</button>
      </form>
      ${data.teams
        .map((t) => {
          const isCap = me && t.captain_id === me.id;
          return `<section class="glass card">
            <div class="row"><h3>${t.name}</h3><span class="chip">${sportLabel(t.sport_type)}</span></div>
            <p class="muted">Join code <strong>${t.join_code}</strong></p>
            <p>${t.members.map((m) => m.username).join(" · ")}</p>
            ${
              isCap
                ? `<button class="btn primary full" data-challenge="${t.id}" data-sport="${t.sport_type}">Challenge another team</button>`
                : `<p class="muted">Only the captain can issue a challenge.</p>`
            }
          </section>`;
        })
        .join("")}
      <div id="challenge-box"></div>
    </div>`;
}

async function openChallenge(teamId, sport) {
  const ops = await api(`/teams/opponents?sport_type=${sport}&team_id=${teamId}`);
  const box = $("challenge-box");
  box.innerHTML = `
    <form id="form-challenge" class="glass card stack">
      <h3>Issue challenge</h3>
      <label>Opponent
        <select name="opponent_team_id" required>
          ${ops.teams.map((t) => `<option value="${t.id}">${t.name}</option>`).join("")}
        </select>
      </label>
      <label>Referee (must be a friend on neither roster)
        <select name="referee_id" required></select>
      </label>
      <button class="btn lime" type="submit">Send challenge</button>
    </form>`;
  if (!ops.teams.length) {
    box.innerHTML = `<div class="glass card"><p>No other ${sportLabel(sport)} teams exist yet.</p></div>`;
    return;
  }
  const form = $("form-challenge");
  async function fillRefs() {
    const opp = form.opponent_team_id.value;
    const refs = await api(`/teams/${teamId}/referees?opponent_team_id=${opp}`);
    form.referee_id.innerHTML = refs.referees.map((r) => `<option value="${r.id}">${r.username}</option>`).join("");
    if (!refs.referees.length) toast("Add a friend who is not on either team to nominate a referee.");
  }
  form.opponent_team_id.addEventListener("change", fillRefs);
  await fillRefs();
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    try {
      const match = await api("/matches/challenge", {
        method: "POST",
        body: JSON.stringify({
          team_id: Number(teamId),
          opponent_team_id: Number(fd.get("opponent_team_id")),
          referee_id: Number(fd.get("referee_id")),
        }),
      });
      toast("Challenge sent. Waiting on the referee.");
      openMatch(match.id);
    } catch (err) {
      toast(err.message);
    }
  });
}

async function loadMatches() {
  const data = await api("/matches");
  $("page-matches").innerHTML = `
    <div class="list">
      ${
        data.matches.length
          ? data.matches
              .map((m) => {
                const isRef = me && m.referee.id === me.id;
                return `<div class="item glass">
                  <div class="row"><strong>${m.team1.name} vs ${m.team2.name}</strong><span class="chip">${m.status}</span></div>
                  <p class="muted">${sportLabel(m.sport_type)} · Ref ${m.referee.username} · ${m.team1_score}-${m.team2_score}</p>
                  <div class="row">
                    <button class="btn ghost" data-open-match="${m.id}">Scoreboard</button>
                    ${isRef && m.status !== "completed" ? `<button class="btn primary" data-open-ref="${m.id}">Ref desk</button>` : ""}
                  </div>
                </div>`;
              })
              .join("")
          : `<p class="muted">No matches yet.</p>`
      }
    </div>`;
}

function eventButtons(sport) {
  if (sport === "basketball") {
    return [
      { type: "1pt", label: "+1 FT" },
      { type: "2pt", label: "+2" },
      { type: "3pt", label: "+3" },
      { type: "foul", label: "Foul" },
    ];
  }
  return [
    { type: "goal", label: "+1 Goal" },
    { type: "yellow_card", label: "Yellow" },
    { type: "red_card", label: "Red" },
    { type: "foul", label: "Foul" },
  ];
}

function renderBoard(match, refMode) {
  const live = match.status === "active";
  const events = (match.events || [])
    .slice()
    .reverse()
    .slice(0, 12)
    .map((e) => `<div>${e.player.username} · ${e.event_type}</div>`)
    .join("");
  const roster = [...match.team1.members, ...match.team2.members];
  const btns = eventButtons(match.sport_type)
    .map((b) => `<button class="btn ${b.type.includes("card") || b.type === "foul" ? "ghost" : "primary"}" data-event="${b.type}">${b.label}</button>`)
    .join("");

  const html = `
    <div class="grid ref-shell">
      <section class="glass scoreboard">
        <p>${live ? '<span class="live-dot"></span>LIVE' : match.status.toUpperCase()} · ${sportLabel(match.sport_type)}</p>
        <div class="score-row">
          <div>
            <div class="team-name">${match.team1.name}</div>
            <div class="score">${match.team1_score}</div>
          </div>
          <div class="muted">VS</div>
          <div>
            <div class="team-name">${match.team2.name}</div>
            <div class="score">${match.team2_score}</div>
          </div>
        </div>
        <p class="muted">Referee ${match.referee.username}${match.mvp ? ` · MVP ${match.mvp.username}` : ""}</p>
        <button class="btn ghost full" type="button" data-back-games="1">Back to games</button>
      </section>
      ${
        refMode
          ? `<section class="glass card">
              <h3>Tap a player, then a stat</h3>
              <div class="player-pick">
                ${roster
                  .map(
                    (p) =>
                      `<button type="button" data-player="${p.id}" class="${selectedPlayerId === p.id ? "selected" : ""}">${p.username} · ${
                        match.team1.members.some((m) => m.id === p.id) ? match.team1.name : match.team2.name
                      }</button>`
                  )
                  .join("")}
              </div>
              <div class="ref-actions">${btns}</div>
              <div class="stack" style="margin-top:12px">
                ${
                  match.status === "pending"
                    ? `<button class="btn lime full" data-start="${match.id}">Start match</button>`
                    : ""
                }
                ${
                  match.status === "active"
                    ? `<button class="btn danger full" data-end="${match.id}">End game & confirm stats</button>`
                    : ""
                }
              </div>
            </section>`
          : ""
      }
      <section class="glass card">
        <h3>Play-by-play</h3>
        <div class="feed">${events || "<p class='muted'>No events yet.</p>"}</div>
      </section>
    </div>`;
  $(refMode ? "page-ref" : "page-board").innerHTML = html;
}

async function openMatch(id, refMode = false) {
  stopPoll();
  currentMatchId = id;
  $("view-app").classList.toggle("ref-mode", !!refMode);
  const match = await api(`/matches/${id}`);
  const iAmRef = me && match.referee.id === me.id;
  if (refMode && !iAmRef) {
    toast("Only the nominated referee can use this desk.");
    refMode = false;
  }
  setPage(refMode ? "ref" : "board", refMode ? "Ref desk" : "Scoreboard");
  selectedPlayerId = null;
  renderBoard(match, refMode);
  if (match.status === "active" || match.status === "pending") {
    pollTimer = setInterval(async () => {
      try {
        const fresh = await api(`/matches/${id}`);
        renderBoard(fresh, refMode);
      } catch (_) {}
    }, 2000);
  }
}

function stopPoll() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  $("view-app").classList.remove("ref-mode");
}

async function loadProfile(id) {
  const p = await api(`/users/${id}`);
  if (p.friends_only) {
    $("page-profile").innerHTML = `<div class="glass card"><h3>${p.username}</h3><p>${p.detail}</p></div>`;
    setPage("profile", p.username);
    return;
  }
  const s = p.stats;
  $("page-profile").innerHTML = `
    <div class="grid">
      <section class="glass card">
        <h3>${p.username}</h3>
        <span class="chip">${sportLabel(p.primary_sport)}</span>
      </section>
      <div class="stats">
        <div class="glass stat"><span>Points / Goals</span><b>${s.points}</b></div>
        <div class="glass stat"><span>Games</span><b>${s.games}</b></div>
        <div class="glass stat"><span>MVPs</span><b>${s.mvp_count}</b></div>
        <div class="glass stat"><span>3PT</span><b>${s.threes}</b></div>
      </div>
    </div>`;
  setPage("profile", p.username);
}

function cricketBlock(e) {
  e.preventDefault();
  $("cricket-modal").classList.remove("hidden");
}

$("form-register").addEventListener("submit", async (e) => {
  if ($("primary-sport").value === "cricket") {
    cricketBlock(e);
    return;
  }
  e.preventDefault();
  const fd = new FormData(e.target);
  try {
    const data = await api("/auth/register", {
      method: "POST",
      body: JSON.stringify({
        username: fd.get("username"),
        password: fd.get("password"),
        primary_sport: fd.get("primary_sport"),
      }),
    });
    store.token = data.token;
    showAuth(false);
    await boot();
  } catch (err) {
    toast(err.message);
  }
});

$("primary-sport").addEventListener("change", () => {
  if ($("primary-sport").value === "cricket") {
    $("cricket-modal").classList.remove("hidden");
    $("primary-sport").value = "basketball";
  }
});

$("cricket-dismiss").addEventListener("click", () => {
  $("cricket-modal").classList.add("hidden");
  $("primary-sport").value = "basketball";
});

$("form-login").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  try {
    const data = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username: fd.get("username"), password: fd.get("password") }),
    });
    store.token = data.token;
    showAuth(false);
    await boot();
  } catch (err) {
    toast(err.message);
  }
});

$("tab-login").addEventListener("click", () => {
  $("form-login").classList.remove("hidden");
  $("form-register").classList.add("hidden");
  $("tab-login").classList.add("active");
  $("tab-register").classList.remove("active");
});

$("tab-register").addEventListener("click", () => {
  $("form-register").classList.remove("hidden");
  $("form-login").classList.add("hidden");
  $("tab-register").classList.add("active");
  $("tab-login").classList.remove("active");
});

$("btn-logout").addEventListener("click", () => {
  store.token = null;
  me = null;
  stopPoll();
  showAuth(true);
});

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", async () => {
    stopPoll();
    const page = tab.dataset.page;
    setPage(page, page[0].toUpperCase() + page.slice(1));
    try {
      if (page === "home") await loadHome();
      if (page === "friends") await loadFriends();
      if (page === "teams") await loadTeams();
      if (page === "matches") await loadMatches();
    } catch (err) {
      toast(err.message);
    }
  });
});

document.body.addEventListener("click", async (e) => {
  const add = e.target.closest("[data-add]");
  const profile = e.target.closest("[data-profile]");
  const challenge = e.target.closest("[data-challenge]");
  const openMatchBtn = e.target.closest("[data-open-match]");
  const openRef = e.target.closest("[data-open-ref]");
  const player = e.target.closest("[data-player]");
  const eventBtn = e.target.closest("[data-event]");
  const start = e.target.closest("[data-start]");
  const end = e.target.closest("[data-end]");
  const backGames = e.target.closest("[data-back-games]");
  try {
    if (add) {
      await api("/friends", { method: "POST", body: JSON.stringify({ username: add.dataset.add }) });
      toast("Friend added");
      await loadFriends();
    }
    if (profile) await loadProfile(Number(profile.dataset.profile));
    if (challenge) await openChallenge(challenge.dataset.challenge, challenge.dataset.sport);
    if (openMatchBtn) await openMatch(Number(openMatchBtn.dataset.openMatch), false);
    if (openRef) await openMatch(Number(openRef.dataset.openRef), true);
    if (player) {
      selectedPlayerId = Number(player.dataset.player);
      document.querySelectorAll("[data-player]").forEach((b) => b.classList.toggle("selected", Number(b.dataset.player) === selectedPlayerId));
    }
    if (eventBtn) {
      if (!selectedPlayerId) {
        toast("Select a player first");
        return;
      }
      if (!currentMatchId) return;
      await api(`/matches/${currentMatchId}/events`, {
        method: "POST",
        body: JSON.stringify({ player_id: selectedPlayerId, event_type: eventBtn.dataset.event }),
      });
      await openMatch(currentMatchId, true);
    }
    if (start) {
      await api(`/matches/${start.dataset.start}/start`, { method: "POST" });
      await openMatch(Number(start.dataset.start), true);
    }
    if (end) {
      const done = await api(`/matches/${end.dataset.end}/end`, { method: "POST" });
      toast(done.mvp ? `Final. MVP: ${done.mvp.username}` : "Final. No scoring MVP.");
      await openMatch(Number(end.dataset.end), true);
    }
    if (backGames) {
      stopPoll();
      setPage("matches", "Games");
      await loadMatches();
    }
  } catch (err) {
    toast(err.message);
  }
});

document.body.addEventListener("submit", async (e) => {
  if (e.target.id === "form-create-team") {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await api("/teams", {
        method: "POST",
        body: JSON.stringify({ name: fd.get("name"), sport_type: fd.get("sport_type") }),
      });
      await loadTeams();
    } catch (err) {
      toast(err.message);
    }
  }
  if (e.target.id === "form-join-team") {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await api("/teams/join", {
        method: "POST",
        body: JSON.stringify({ join_code: String(fd.get("join_code")).toUpperCase() }),
      });
      await loadTeams();
    } catch (err) {
      toast(err.message);
    }
  }
});

async function boot() {
  if (!store.token) {
    showAuth(true);
    return;
  }
  try {
    showAuth(false);
    setPage("home", "Home");
    await loadHome();
  } catch (_) {
    store.token = null;
    showAuth(true);
  }
}

boot();
