/* ===========================================================
   스마트 영농관리 웹앱 - 프론트엔드 스크립트
=========================================================== */
(function () {
  "use strict";

  // -----------------------------------------------------------
  // 공통 유틸
  // -----------------------------------------------------------
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  function toast(msg) {
    var el = $("#toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { el.classList.remove("show"); }, 2200);
  }

  function fmtNumber(n) {
    if (n === null || n === undefined || isNaN(n)) return "0";
    return Math.round(n).toLocaleString("ko-KR");
  }

  function icons() {
    if (window.lucide) window.lucide.createIcons();
  }

  async function api(url, opts) {
    opts = opts || {};
    var options = { method: opts.method || "GET", headers: {}, credentials: "same-origin" };
    if (opts.body instanceof FormData) {
      options.body = opts.body;
    } else if (opts.body) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(opts.body);
    }
    var res = await fetch(url, options);
    var data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok) {
      var msg = (data && data.msg) ? data.msg : "요청 처리 중 오류가 발생했습니다.";
      throw new Error(msg);
    }
    return data;
  }

  // =============================================================
  // 로그인 / 회원가입 페이지 로직
  // =============================================================
  function initAuthPage() {
    icons();
    var tabs = $all(".auth-tab");
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        tabs.forEach(function (t) { t.classList.remove("active"); });
        tab.classList.add("active");
        var target = tab.getAttribute("data-tab");
        $("#loginForm").classList.toggle("hidden", target !== "login");
        $("#registerForm").classList.toggle("hidden", target !== "register");
      });
    });

    $("#loginForm").addEventListener("submit", async function (e) {
      e.preventDefault();
      var errBox = $("#loginError");
      errBox.textContent = "";
      try {
        await api("/api/login", {
          method: "POST",
          body: { email: $("#loginEmail").value, password: $("#loginPassword").value }
        });
        window.location.href = "/app";
      } catch (err) {
        errBox.textContent = err.message;
      }
    });

    $("#registerForm").addEventListener("submit", async function (e) {
      e.preventDefault();
      var errBox = $("#registerError");
      errBox.textContent = "";
      try {
        await api("/api/register", {
          method: "POST",
          body: {
            name: $("#regName").value,
            email: $("#regEmail").value,
            password: $("#regPassword").value,
            phone: $("#regPhone").value,
            farm_name: $("#regFarmName").value,
            region: $("#regRegion").value
          }
        });
        window.location.href = "/app";
      } catch (err) {
        errBox.textContent = err.message;
      }
    });

    $("#demoAdminBtn").addEventListener("click", async function () {
      $("#loginEmail").value = "cksdudd102@naver.com";
      $("#loginPassword").value = "1q2w3e4r~@";
      try {
        await api("/api/login", { method: "POST", body: { email: "cksdudd102@naver.com", password: "1q2w3e4r~@" } });
        window.location.href = "/app";
      } catch (err) { $("#loginError").textContent = err.message; }
    });
    $("#demoFarmerBtn").addEventListener("click", async function () {
      $("#loginEmail").value = "farmer@farm.com";
      $("#loginPassword").value = "farm1234";
      try {
        await api("/api/login", { method: "POST", body: { email: "farmer@farm.com", password: "farm1234" } });
        window.location.href = "/app";
      } catch (err) { $("#loginError").textContent = err.message; }
    });
  }

  // =============================================================
  // 메인 앱(SPA) 로직
  // =============================================================
  var STATE = {
    user: null,
    crops: [],
    tasks: [],
    inventory: [],
    shipments: [],
    journals: [],
    posts: [],
    diagnoses: [],
    rda: [],
    pesticides: [],
    support: [],
    safety: [],
    users: [],
    plans: [],
    grades: [],
    promoCodes: [],
    links: [],
    mySubscription: null,
    activityLogs: [],
    billingCycle: "monthly",
    appliedPromo: null,
    postFilter: { category: "전체", q: "", page: 1 },
    selectedUserIds: []
  };

  var PAGE_TITLES = {
    dashboard: "대시보드", crops: "작물 관리", journals: "영농 일지", tasks: "작업 일정",
    inventory: "재고 관리", diagnosis: "AI 작물 진단", market: "농산물 시세", weather: "날씨 예보",
    pesticide: "농약 정보", support: "정부 지원사업", rda: "농업진흥청 새소식",
    community: "커뮤니티", shipments: "출하 관리", safety: "농작업 안전", admin: "사용자 관리",
    pricing: "요금제", plans: "요금제 관리", links: "농업 링크 모음", grades: "등급 관리",
    promos: "프로모션 코드 관리", linksAdmin: "농업 링크 관리"
  };

  var WEATHER_ICON_MAP = {
    "맑음": "sun", "구름조금": "cloud-sun", "흐림": "cloud", "비": "cloud-rain",
    "소나기": "cloud-rain-wind", "눈": "cloud-snow"
  };

  var charts = { journal: null, cropStatus: null };

  function navigateTo(page) {
    $all(".page").forEach(function (p) { p.classList.remove("active"); });
    var target = $("#page-" + page);
    if (target) target.classList.add("active");

    $all(".nav-link").forEach(function (n) { n.classList.toggle("active", n.getAttribute("data-page") === page); });
    $all(".bnav-link").forEach(function (n) { n.classList.toggle("active", n.getAttribute("data-page") === page); });

    var titleEl = $("#mobileHeaderTitle");
    if (titleEl) titleEl.textContent = PAGE_TITLES[page] || "";

    closeMoreSheet();
    loadPageData(page);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function closeMoreSheet() {
    $("#moreSheet").classList.remove("open");
  }

  function bindNav() {
    $all("[data-page]").forEach(function (el) {
      el.addEventListener("click", function (e) {
        var page = el.getAttribute("data-page");
        if (page === "more") {
          $("#moreSheet").classList.add("open");
          return;
        }
        e.preventDefault();
        navigateTo(page);
      });
    });
    $("#moreSheetBackdrop").addEventListener("click", closeMoreSheet);

    $("#logoutBtn").addEventListener("click", doLogout);
    $("#mobileLogoutBtn").addEventListener("click", doLogout);
    $("#moreLogoutBtn").addEventListener("click", doLogout);

    $all(".modal-close").forEach(function (btn) {
      btn.addEventListener("click", function () {
        btn.closest(".modal").classList.remove("open");
      });
    });
    $all("[data-modal]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        openModal(btn.getAttribute("data-modal"));
      });
    });
    $all(".modal").forEach(function (m) {
      m.addEventListener("click", function (e) {
        if (e.target === m) m.classList.remove("open");
      });
    });
  }

  function openModal(id, resetForm) {
    var modal = $("#" + id);
    if (!modal) return;
    if (resetForm !== false) {
      var form = $("form", modal);
      if (form) form.reset();
      var hiddenId = $("input[type=hidden]", modal);
      if (hiddenId) hiddenId.value = "";
      var titleEl = $(".modal-header h3", modal);
      if (titleEl && titleEl.id.endsWith("Title")) {
        var base = titleEl.textContent.replace("수정", "등록").replace("편집", "작성");
      }
    }
    populateSelectOptions();
    modal.classList.add("open");
  }

  async function doLogout() {
    try { await api("/api/logout", { method: "POST" }); } catch (e) {}
    window.location.href = "/";
  }

  function populateSelectOptions() {
    var cropOptions = '<option value="">선택 안함</option>' +
      STATE.crops.map(function (c) { return '<option value="' + c.id + '">' + c.name + " (" + (c.field_location || "") + ")</option>"; }).join("");
    ["journalCropId", "taskCropId", "shipmentCropId"].forEach(function (id) {
      var el = $("#" + id);
      if (el) el.innerHTML = cropOptions;
    });
  }

  // -------------------------------------------------------------
  // 페이지별 데이터 로딩 & 렌더링
  // -------------------------------------------------------------
  async function loadPageData(page) {
    try {
      if (page === "dashboard") return renderDashboard();
      if (page === "crops") return renderCrops();
      if (page === "journals") return renderJournals();
      if (page === "tasks") return renderTasks();
      if (page === "inventory") return renderInventory();
      if (page === "diagnosis") return renderDiagnosisHistory();
      if (page === "market") return renderMarket();
      if (page === "weather") return renderWeather();
      if (page === "pesticide") return renderPesticides();
      if (page === "support") return renderSupport();
      if (page === "rda") return renderRda();
      if (page === "community") return renderCommunity();
      if (page === "shipments") return renderShipments();
      if (page === "safety") return renderSafety();
      if (page === "admin") return renderAdmin();
      if (page === "pricing") return renderPricing();
      if (page === "plans") return renderPlanManagement();
      if (page === "links") return renderLinks();
      if (page === "grades") return renderGradeManagement();
      if (page === "promos") return renderPromoManagement();
      if (page === "linksAdmin") return renderLinkManagement();
    } catch (err) {
      toast(err.message || "데이터를 불러오지 못했습니다.");
    }
  }

  // ---------- 대시보드 ----------
  async function renderDashboard() {
    var res = await api("/api/dashboard/summary");
    var d = res.data;
    $("#statCrops").textContent = d.growing_crops;
    $("#statTasks").textContent = d.pending_tasks;
    $("#statLowStock").textContent = d.low_stock;
    $("#statShipment").textContent = fmtNumber(d.total_shipment_amount) + "원";
    $("#dashUserName").textContent = STATE.user.name;
    var dashGradeEl = $("#dashUserGrade");
    if (dashGradeEl) {
      dashGradeEl.textContent = STATE.user.grade_name || "일반회원";
      dashGradeEl.style.background = STATE.user.grade_color || "#8a9a8a";
    }

    var upcomingList = $("#upcomingTasksList");
    upcomingList.innerHTML = d.upcoming_tasks.length ? d.upcoming_tasks.map(function (t) {
      return '<li><span>' + escapeHtml(t.title) + '</span><span class="tag">' + (t.due_date || "-") + "</span></li>";
    }).join("") : '<div class="empty-msg">등록된 작업이 없습니다.</div>';

    var journalList = $("#recentJournalsList");
    journalList.innerHTML = d.recent_journals.length ? d.recent_journals.map(function (j) {
      return '<li><span>' + escapeHtml(j.work_type || "기록") + (j.crop_name ? " · " + escapeHtml(j.crop_name) : "") + '</span><span class="muted">' + j.date + "</span></li>";
    }).join("") : '<div class="empty-msg">작성된 일지가 없습니다.</div>';

    renderJournalChart(d.chart_labels, d.chart_counts);
    renderCropStatusChart(d.crop_status_counts);
    renderDashPlanCard();
    icons();
  }

  var PLAN_CODE_LABEL = { free: "무료", starter: "스타터", pro: "프로", enterprise: "기업" };
  var SUB_STATUS_LABEL = { active: "활성", cancelled: "해지", expired: "만료" };

  async function renderDashPlanCard() {
    var box = $("#dashPlanCardBody");
    if (!box) return;
    try {
      var res = await api("/api/subscriptions/me");
      STATE.mySubscription = res.data;
      var s = res.data;
      box.innerHTML =
        '<div class="plan-card-info">' +
        '<h4>' + escapeHtml(s.plan_name || "무료") + '<span class="plan-badge plan-' + escapeHtml(s.plan_code || "free") + '">' + escapeHtml(PLAN_CODE_LABEL[s.plan_code] || s.plan_code || "") + '</span></h4>' +
        '<p>' + (s.expiry_date ? "만료일: " + s.expiry_date : "만료일 없음 (무료 요금제)") + '</p>' +
        '</div>' +
        '<span class="plan-card-status ' + escapeHtml(s.status || "active") + '">' + escapeHtml(SUB_STATUS_LABEL[s.status] || s.status || "") + '</span>';
    } catch (err) {
      box.innerHTML = '<div class="empty-msg">요금제 정보를 불러오지 못했습니다.</div>';
    }
  }

  function renderJournalChart(labels, counts) {
    var ctx = $("#journalChart");
    if (!ctx || !window.Chart) return;
    if (charts.journal) charts.journal.destroy();
    charts.journal = new Chart(ctx, {
      type: "bar",
      data: { labels: labels, datasets: [{ label: "일지 기록 수", data: counts, backgroundColor: "#3d8b42", borderRadius: 6 }] },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } } }
    });
  }

  function renderCropStatusChart(statusCounts) {
    var ctx = $("#cropStatusChart");
    if (!ctx || !window.Chart) return;
    var labels = Object.keys(statusCounts);
    var values = labels.map(function (k) { return statusCounts[k]; });
    if (!labels.length) { labels = ["데이터 없음"]; values = [1]; }
    if (charts.cropStatus) charts.cropStatus.destroy();
    charts.cropStatus = new Chart(ctx, {
      type: "doughnut",
      data: {
        labels: labels,
        datasets: [{ data: values, backgroundColor: ["#3d8b42", "#f0a020", "#9aa39a", "#3b82c4", "#e5484d"] }]
      },
      options: { plugins: { legend: { position: "bottom" } } }
    });
  }

  // ---------- 작물 관리 ----------
  async function renderCrops() {
    var res = await api("/api/crops");
    STATE.crops = res.data;
    var list = $("#cropList");
    if (!STATE.crops.length) { list.innerHTML = '<div class="empty-msg">등록된 작물이 없습니다. 새 작물을 등록해보세요.</div>'; return; }
    list.innerHTML = STATE.crops.map(function (c) {
      var statusBadge = c.status === "재배중" ? "badge-green" : c.status === "수확완료" ? "badge-blue" : "badge-gray";
      return '<div class="item-card">' +
        (c.image ? '<img class="item-card-img" src="/static/' + c.image + '">' :
          '<div class="item-card-img-placeholder"><i data-lucide="leaf"></i></div>') +
        '<div class="item-card-body">' +
        '<div class="item-card-title">' + escapeHtml(c.name) + '<span class="badge ' + statusBadge + '">' + c.status + '</span></div>' +
        '<div class="item-card-meta">품종: ' + escapeHtml(c.variety || "-") + '<br>위치: ' + escapeHtml(c.field_location || "-") +
        (c.area ? ' (' + c.area + '평)' : '') + '<br>정식일: ' + (c.planting_date || "-") + ' → 수확예정: ' + (c.expected_harvest_date || "-") +
        (c.memo ? '<br>메모: ' + escapeHtml(c.memo) : '') + '</div></div>' +
        '<div class="item-card-actions">' +
        '<button class="btn btn-outline btn-sm" onclick="FarmApp.editCrop(' + c.id + ')"><i data-lucide="pencil"></i> 수정</button>' +
        '<button class="btn btn-danger btn-sm" onclick="FarmApp.deleteCrop(' + c.id + ')"><i data-lucide="trash-2"></i> 삭제</button>' +
        '</div></div>';
    }).join("");
    icons();
  }

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  window.FarmApp = window.FarmApp || {};

  FarmApp.editCrop = function (id) {
    var c = STATE.crops.find(function (x) { return x.id === id; });
    if (!c) return;
    openModal("cropModal", false);
    $("#cropModalTitle").textContent = "작물 정보 수정";
    $("#cropId").value = c.id;
    $("#cropName").value = c.name || "";
    $("#cropVariety").value = c.variety || "";
    $("#cropLocation").value = c.field_location || "";
    $("#cropArea").value = c.area || "";
    $("#cropPlantingDate").value = c.planting_date || "";
    $("#cropHarvestDate").value = c.expected_harvest_date || "";
    $("#cropStatus").value = c.status || "재배중";
    $("#cropMemo").value = c.memo || "";
  };

  FarmApp.deleteCrop = async function (id) {
    if (!confirm("이 작물 정보를 삭제하시겠습니까?")) return;
    await api("/api/crops/" + id, { method: "DELETE" });
    toast("작물이 삭제되었습니다.");
    renderCrops();
  };

  $("body") && document.addEventListener("submit", async function (e) {
    if (e.target.id === "cropForm") {
      e.preventDefault();
      var id = $("#cropId").value;
      var fd = new FormData();
      fd.append("name", $("#cropName").value);
      fd.append("variety", $("#cropVariety").value);
      fd.append("field_location", $("#cropLocation").value);
      fd.append("area", $("#cropArea").value);
      fd.append("planting_date", $("#cropPlantingDate").value);
      fd.append("expected_harvest_date", $("#cropHarvestDate").value);
      fd.append("status", $("#cropStatus").value);
      fd.append("memo", $("#cropMemo").value);
      var imgFile = $("#cropImage").files[0];
      if (imgFile) fd.append("image", imgFile);
      try {
        if (id) await api("/api/crops/" + id, { method: "PUT", body: fd });
        else await api("/api/crops", { method: "POST", body: fd });
        $("#cropModal").classList.remove("open");
        toast("작물 정보가 저장되었습니다.");
        renderCrops();
        renderDashboard();
      } catch (err) { toast(err.message); }
    }
  });

  // ---------- 영농 일지 ----------
  async function renderJournals() {
    var res = await api("/api/journals");
    STATE.journals = res.data;
    var list = $("#journalList");
    if (!STATE.journals.length) { list.innerHTML = '<div class="empty-msg">작성된 영농 일지가 없습니다.</div>'; return; }
    list.innerHTML = STATE.journals.map(function (j) {
      var dparts = (j.date || "").split("-");
      return '<div class="timeline-item">' +
        '<div class="timeline-date"><strong>' + (dparts[2] || "-") + '</strong><small>' + (dparts[1] ? dparts[1] + "월" : "") + '</small></div>' +
        '<div class="timeline-body">' +
        '<h4>' + escapeHtml(j.work_type || "기록") + (j.crop_name ? " · " + escapeHtml(j.crop_name) : "") +
        '<span class="badge badge-gray" style="margin-left:6px;">' + escapeHtml(j.weather || "") + '</span></h4>' +
        '<p>' + escapeHtml(j.content || "") + '</p>' +
        (j.image ? '<img src="/static/' + j.image + '">' : "") +
        '<div class="timeline-actions">' +
        '<button class="btn btn-outline btn-sm" onclick="FarmApp.editJournal(' + j.id + ')"><i data-lucide="pencil"></i> 수정</button>' +
        '<button class="btn btn-danger btn-sm" onclick="FarmApp.deleteJournal(' + j.id + ')"><i data-lucide="trash-2"></i> 삭제</button>' +
        '</div></div></div>';
    }).join("");
    icons();
  }

  FarmApp.editJournal = function (id) {
    var j = STATE.journals.find(function (x) { return x.id === id; });
    if (!j) return;
    openModal("journalModal", false);
    populateSelectOptions();
    $("#journalModalTitle").textContent = "영농 일지 수정";
    $("#journalId").value = j.id;
    $("#journalCropId").value = j.crop_id || "";
    $("#journalDate").value = j.date || "";
    $("#journalWeather").value = j.weather || "맑음";
    $("#journalWorkType").value = j.work_type || "파종";
    $("#journalContent").value = j.content || "";
  };

  FarmApp.deleteJournal = async function (id) {
    if (!confirm("이 일지를 삭제하시겠습니까?")) return;
    await api("/api/journals/" + id, { method: "DELETE" });
    toast("일지가 삭제되었습니다.");
    renderJournals();
  };

  document.addEventListener("submit", async function (e) {
    if (e.target.id === "journalForm") {
      e.preventDefault();
      var id = $("#journalId").value;
      var fd = new FormData();
      fd.append("crop_id", $("#journalCropId").value);
      fd.append("date", $("#journalDate").value || new Date().toISOString().slice(0, 10));
      fd.append("weather", $("#journalWeather").value);
      fd.append("work_type", $("#journalWorkType").value);
      fd.append("content", $("#journalContent").value);
      var imgFile = $("#journalImage").files[0];
      if (imgFile) fd.append("image", imgFile);
      try {
        if (id) await api("/api/journals/" + id, { method: "PUT", body: fd });
        else await api("/api/journals", { method: "POST", body: fd });
        $("#journalModal").classList.remove("open");
        toast("영농 일지가 저장되었습니다.");
        renderJournals();
        renderDashboard();
      } catch (err) { toast(err.message); }
    }
  });

  // ---------- 작업 일정 ----------
  async function renderTasks() {
    var res = await api("/api/tasks");
    STATE.tasks = res.data;
    ["예정", "진행중", "완료"].forEach(function (status) {
      var col = $("#col-" + status);
      var items = STATE.tasks.filter(function (t) { return t.status === status; });
      col.innerHTML = items.length ? items.map(function (t) {
        var prioClass = t.priority === "높음" ? "badge-red" : t.priority === "낮음" ? "badge-gray" : "badge-amber";
        return '<div class="task-item">' +
          '<div class="task-item-title">' + escapeHtml(t.title) + '</div>' +
          '<div class="task-item-meta"><span class="badge ' + prioClass + '">' + t.priority + '</span>' +
          (t.due_date ? '<span>' + t.due_date + '</span>' : '') +
          (t.crop_name ? '<span>· ' + escapeHtml(t.crop_name) + '</span>' : '') + '</div>' +
          (t.memo ? '<div class="item-card-meta" style="margin-top:6px;">' + escapeHtml(t.memo) + '</div>' : '') +
          '<div class="task-item-actions">' +
          '<select onchange="FarmApp.updateTaskStatus(' + t.id + ', this.value)">' +
          ["예정", "진행중", "완료"].map(function (s) { return '<option value="' + s + '" ' + (s === t.status ? "selected" : "") + '>' + s + '</option>'; }).join("") +
          '</select>' +
          '<button class="btn btn-outline btn-sm" onclick="FarmApp.editTask(' + t.id + ')"><i data-lucide="pencil"></i></button>' +
          '<button class="btn btn-danger btn-sm" onclick="FarmApp.deleteTask(' + t.id + ')"><i data-lucide="trash-2"></i></button>' +
          '</div></div>';
      }).join("") : '<div class="empty-msg">항목 없음</div>';
    });
    icons();
  }

  FarmApp.updateTaskStatus = async function (id, status) {
    await api("/api/tasks/" + id, { method: "PUT", body: { status: status } });
    toast("작업 상태가 변경되었습니다.");
    renderTasks();
    renderDashboard();
  };

  FarmApp.editTask = function (id) {
    var t = STATE.tasks.find(function (x) { return x.id === id; });
    if (!t) return;
    openModal("taskModal", false);
    populateSelectOptions();
    $("#taskModalTitle").textContent = "작업 수정";
    $("#taskId").value = t.id;
    $("#taskTitle").value = t.title || "";
    $("#taskCropId").value = t.crop_id || "";
    $("#taskDueDate").value = t.due_date || "";
    $("#taskPriority").value = t.priority || "보통";
    $("#taskStatus").value = t.status || "예정";
    $("#taskMemo").value = t.memo || "";
  };

  FarmApp.deleteTask = async function (id) {
    if (!confirm("이 작업을 삭제하시겠습니까?")) return;
    await api("/api/tasks/" + id, { method: "DELETE" });
    toast("작업이 삭제되었습니다.");
    renderTasks();
    renderDashboard();
  };

  document.addEventListener("submit", async function (e) {
    if (e.target.id === "taskForm") {
      e.preventDefault();
      var id = $("#taskId").value;
      var body = {
        title: $("#taskTitle").value, crop_id: $("#taskCropId").value || null,
        due_date: $("#taskDueDate").value, priority: $("#taskPriority").value,
        status: $("#taskStatus").value, memo: $("#taskMemo").value
      };
      try {
        if (id) await api("/api/tasks/" + id, { method: "PUT", body: body });
        else await api("/api/tasks", { method: "POST", body: body });
        $("#taskModal").classList.remove("open");
        toast("작업이 저장되었습니다.");
        renderTasks();
        renderDashboard();
      } catch (err) { toast(err.message); }
    }
  });

  // ---------- 재고 관리 ----------
  async function renderInventory() {
    var res = await api("/api/inventory");
    STATE.inventory = res.data;
    var tbody = $("#inventoryTable tbody");
    tbody.innerHTML = STATE.inventory.length ? STATE.inventory.map(function (i) {
      var low = i.quantity <= 5;
      return '<tr>' +
        '<td>' + escapeHtml(i.name) + '</td>' +
        '<td>' + escapeHtml(i.category || "-") + '</td>' +
        '<td>' + (low ? '<span class="badge badge-red">' : '') + i.quantity + " " + escapeHtml(i.unit || "") + (low ? '</span>' : '') + '</td>' +
        '<td>' + escapeHtml(i.location || "-") + '</td>' +
        '<td>' + (i.expiry_date || "-") + '</td>' +
        '<td class="row-actions">' +
        '<button class="btn btn-outline btn-sm" onclick="FarmApp.editInventory(' + i.id + ')"><i data-lucide="pencil"></i></button>' +
        '<button class="btn btn-danger btn-sm" onclick="FarmApp.deleteInventory(' + i.id + ')"><i data-lucide="trash-2"></i></button>' +
        '</td></tr>';
    }).join("") : '<tr><td colspan="6" class="empty-msg">등록된 재고가 없습니다.</td></tr>';
    icons();
  }

  FarmApp.editInventory = function (id) {
    var i = STATE.inventory.find(function (x) { return x.id === id; });
    if (!i) return;
    openModal("inventoryModal", false);
    $("#inventoryModalTitle").textContent = "재고 수정";
    $("#inventoryId").value = i.id;
    $("#invName").value = i.name || "";
    $("#invCategory").value = i.category || "종자";
    $("#invQuantity").value = i.quantity || 0;
    $("#invUnit").value = i.unit || "";
    $("#invLocation").value = i.location || "";
    $("#invExpiry").value = i.expiry_date || "";
    $("#invMemo").value = i.memo || "";
  };

  FarmApp.deleteInventory = async function (id) {
    if (!confirm("이 재고 항목을 삭제하시겠습니까?")) return;
    await api("/api/inventory/" + id, { method: "DELETE" });
    toast("재고가 삭제되었습니다.");
    renderInventory();
  };

  document.addEventListener("submit", async function (e) {
    if (e.target.id === "inventoryForm") {
      e.preventDefault();
      var id = $("#inventoryId").value;
      var body = {
        name: $("#invName").value, category: $("#invCategory").value,
        quantity: $("#invQuantity").value, unit: $("#invUnit").value,
        location: $("#invLocation").value, expiry_date: $("#invExpiry").value,
        memo: $("#invMemo").value
      };
      try {
        if (id) await api("/api/inventory/" + id, { method: "PUT", body: body });
        else await api("/api/inventory", { method: "POST", body: body });
        $("#inventoryModal").classList.remove("open");
        toast("재고 정보가 저장되었습니다.");
        renderInventory();
        renderDashboard();
      } catch (err) { toast(err.message); }
    }
  });

  // ---------- AI 작물 진단 ----------
  document.addEventListener("submit", async function (e) {
    if (e.target.id === "diagnosisForm") {
      e.preventDefault();
      var fd = new FormData();
      fd.append("crop_name", $("#diagCropName").value || "미지정");
      var imgFile = $("#diagImage").files[0];
      if (!imgFile) { toast("진단할 사진을 업로드해주세요."); return; }
      fd.append("image", imgFile);
      try {
        var res = await api("/api/diagnoses", { method: "POST", body: fd });
        showDiagResult(res.data);
        renderDiagnosisHistory();
        e.target.reset();
      } catch (err) { toast(err.message); }
    }
  });

  function showDiagResult(d) {
    var box = $("#diagResult");
    box.className = "diag-result severity-" + d.severity;
    box.innerHTML = '<h4>진단 결과: ' + escapeHtml(d.disease_name) + ' <span class="badge badge-gray">신뢰도 ' + d.confidence + '%</span></h4>' +
      '<div class="diag-result-row"><span>심각도</span><strong>' + escapeHtml(d.severity) + '</strong></div>' +
      '<div class="diag-result-row"><span>조치 권고</span></div>' +
      '<p style="margin-top:4px;font-size:13px;">' + escapeHtml(d.advice) + '</p>';
    box.classList.remove("hidden");
  }

  async function renderDiagnosisHistory() {
    var res = await api("/api/diagnoses");
    STATE.diagnoses = res.data;
    var list = $("#diagnosisHistory");
    if (!STATE.diagnoses.length) { list.innerHTML = '<div class="empty-msg">진단 이력이 없습니다.</div>'; return; }
    list.innerHTML = STATE.diagnoses.map(function (d) {
      var badgeClass = d.severity === "위험" ? "badge-red" : d.severity === "정상" ? "badge-green" : "badge-amber";
      return '<div class="item-card">' +
        (d.image ? '<img class="item-card-img" src="/static/' + d.image + '">' : '<div class="item-card-img-placeholder"><i data-lucide="scan-eye"></i></div>') +
        '<div class="item-card-body">' +
        '<div class="item-card-title">' + escapeHtml(d.crop_name || "-") + '<span class="badge ' + badgeClass + '">' + escapeHtml(d.severity) + '</span></div>' +
        '<div class="item-card-meta">' + escapeHtml(d.disease_name) + ' (신뢰도 ' + d.confidence + '%)<br>' + escapeHtml(d.advice) + '<br><small>' + d.created_at + '</small></div></div>' +
        '<div class="item-card-actions"><button class="btn btn-danger btn-sm" onclick="FarmApp.deleteDiagnosis(' + d.id + ')"><i data-lucide="trash-2"></i> 삭제</button></div></div>';
    }).join("");
    icons();
  }

  FarmApp.deleteDiagnosis = async function (id) {
    if (!confirm("이 진단 기록을 삭제하시겠습니까?")) return;
    await api("/api/diagnoses/" + id, { method: "DELETE" });
    toast("진단 기록이 삭제되었습니다.");
    renderDiagnosisHistory();
  };

  // ---------- 농산물 시세 ----------
  async function renderMarket() {
    var res = await api("/api/market");
    $("#marketDate").textContent = res.date + " 기준 (모의 데이터)";
    var tbody = $("#marketTableBody");
    tbody.innerHTML = res.data.map(function (m) {
      var color = m.trend === "up" ? "#e5484d" : m.trend === "down" ? "#3b82c4" : "#6b746b";
      var arrow = m.trend === "up" ? "▲" : m.trend === "down" ? "▼" : "-";
      return '<tr><td>' + escapeHtml(m.name) + '</td><td>' + escapeHtml(m.unit) + '</td><td>' + fmtNumber(m.price) + '원</td>' +
        '<td style="color:' + color + ';font-weight:700;">' + arrow + ' ' + Math.abs(m.change_pct) + '%</td></tr>';
    }).join("");
  }

  // ---------- 날씨 예보 ----------
  async function renderWeather(region) {
    region = region || $("#weatherRegionInput").value || "전국";
    var res = await api("/api/weather?region=" + encodeURIComponent(region));
    var grid = $("#weatherGrid");
    grid.innerHTML = res.data.map(function (w) {
      var icon = WEATHER_ICON_MAP[w.condition] || "cloud";
      return '<div class="weather-card"><div class="w-day">' + w.day + '요일</div><div class="w-date">' + w.date.slice(5) + '</div>' +
        '<i data-lucide="' + icon + '"></i><div>' + w.condition + '</div>' +
        '<div class="w-temp">' + w.temp_max + '&deg; <span class="low">' + w.temp_min + '&deg;</span></div>' +
        '<div class="w-rain">강수확률 ' + w.rain_prob + '%</div></div>';
    }).join("");
    icons();
  }

  // ---------- 농약 정보 ----------
  async function renderPesticides(q) {
    var res = await api("/api/pesticides" + (q ? "?q=" + encodeURIComponent(q) : ""));
    STATE.pesticides = res.data;
    var list = $("#pesticideList");
    if (!STATE.pesticides.length) { list.innerHTML = '<div class="empty-msg">검색 결과가 없습니다.</div>'; return; }
    list.innerHTML = STATE.pesticides.map(function (p) {
      return '<div class="item-card"><div class="item-card-body">' +
        '<div class="item-card-title">' + escapeHtml(p.name) + '<span class="badge badge-blue">' + escapeHtml(p.type) + '</span></div>' +
        '<div class="item-card-meta">방제 대상: ' + escapeHtml(p.target) + '<br>적용 작물: ' + escapeHtml(p.crops) +
        '<br>안전사용기간: ' + escapeHtml(p.safety_period) + '<br>희석배수: ' + escapeHtml(p.dilution) + '</div></div></div>';
    }).join("");
  }

  // ---------- 정부 지원사업 ----------
  async function renderSupport() {
    var res = await api("/api/support-programs");
    STATE.support = res.data;
    var list = $("#supportList");
    list.innerHTML = STATE.support.map(function (s) {
      return '<div class="item-card"><div class="item-card-body">' +
        '<div class="item-card-title">' + escapeHtml(s.title) + '<span class="badge badge-green">' + escapeHtml(s.status) + '</span></div>' +
        '<div class="item-card-meta">주관: ' + escapeHtml(s.agency) + '<br>기간: ' + escapeHtml(s.period) +
        '<br>대상: ' + escapeHtml(s.target) + '<br>' + escapeHtml(s.content) + '</div></div></div>';
    }).join("");
  }

  // ---------- 농업진흥청 새소식 ----------
  async function renderRda() {
    var res = await api("/api/rda");
    STATE.rda = res.data;
    var list = $("#rdaList");
    if (!STATE.rda.length) { list.innerHTML = '<div class="empty-msg">등록된 소식이 없습니다.</div>'; return; }
    list.innerHTML = STATE.rda.map(function (n) {
      var dparts = (n.notice_date || "").split("-");
      return '<div class="timeline-item"><div class="timeline-date"><strong>' + (dparts[2] || "-") + '</strong><small>' + (dparts[1] ? dparts[1] + "월" : "") + '</small></div>' +
        '<div class="timeline-body"><h4>' + escapeHtml(n.title) + ' <span class="badge badge-green">' + escapeHtml(n.category) + '</span></h4>' +
        '<p>' + escapeHtml(n.content || "") + '</p>' +
        (STATE.user.role === "admin" ? '<div class="timeline-actions"><button class="btn btn-danger btn-sm" onclick="FarmApp.deleteRda(' + n.id + ')"><i data-lucide="trash-2"></i> 삭제</button></div>' : '') +
        '</div></div>';
    }).join("");
    icons();
  }

  FarmApp.deleteRda = async function (id) {
    if (!confirm("이 소식을 삭제하시겠습니까?")) return;
    await api("/api/rda/" + id, { method: "DELETE" });
    toast("소식이 삭제되었습니다.");
    renderRda();
  };

  document.addEventListener("submit", async function (e) {
    if (e.target.id === "rdaForm") {
      e.preventDefault();
      var body = {
        category: $("#rdaCategory").value, title: $("#rdaTitle").value,
        notice_date: $("#rdaDate").value, content: $("#rdaContent").value,
        source_url: $("#rdaSourceUrl").value
      };
      try {
        await api("/api/rda", { method: "POST", body: body });
        $("#rdaModal").classList.remove("open");
        toast("새소식이 등록되었습니다.");
        renderRda();
      } catch (err) { toast(err.message); }
    }
  });

  // ---------- 커뮤니티 ----------
  async function renderCommunity() {
    var f = STATE.postFilter;
    var params = new URLSearchParams();
    if (f.category && f.category !== "전체") params.set("category", f.category);
    if (f.q) params.set("q", f.q);
    params.set("page", f.page);
    params.set("per_page", 10);
    var res = await api("/api/posts?" + params.toString());
    STATE.posts = res.data;
    var pinned = res.pinned || [];
    var tbody = $("#postTableBody");
    var total = res.total || 0;

    if (!STATE.posts.length && !pinned.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty-msg">등록된 게시글이 없습니다.</td></tr>';
    } else {
      var rows = [];
      var startNum = total - (f.page - 1) * 10;
      pinned.forEach(function (p) {
        rows.push(postRowHtml(p, "고정", true));
      });
      STATE.posts.filter(function (p) { return !p.is_pinned; }).forEach(function (p, idx) {
        rows.push(postRowHtml(p, startNum - idx, false));
      });
      tbody.innerHTML = rows.join("");
    }
    renderPostPagination(res.total_pages || 1, f.page);
    icons();
  }

  function postRowHtml(p, num, isPinned) {
    var canManage = STATE.user.role === "admin" || STATE.user.id === p.user_id;
    return '<tr class="' + (isPinned ? "pinned-row" : "") + '" onclick="FarmApp.openPostDetail(' + p.id + ')">' +
      '<td class="col-num">' + (isPinned ? '<span class="badge badge-amber">공지</span>' : num) + '</td>' +
      '<td class="col-title">' + escapeHtml(p.title) +
      (p.category && p.category !== "자유" ? ' <span class="badge badge-green">' + escapeHtml(p.category) + '</span>' : '') +
      '</td><td>' + escapeHtml(p.author_name) + '</td><td>' + p.created_date + '</td><td>' + p.views + '</td>' +
      '<td>' + (p.has_attachment ? '<i data-lucide="paperclip"></i>' : '-') + '</td></tr>';
  }

  function renderPostPagination(totalPages, currentPage) {
    var el = $("#postPagination");
    if (!el) return;
    if (totalPages <= 1) { el.innerHTML = ""; return; }
    var html = "";
    for (var i = 1; i <= totalPages; i++) {
      html += '<button type="button" class="page-btn ' + (i === currentPage ? "active" : "") + '" onclick="FarmApp.gotoPostPage(' + i + ')">' + i + '</button>';
    }
    el.innerHTML = html;
  }

  FarmApp.gotoPostPage = function (page) {
    STATE.postFilter.page = page;
    renderCommunity();
  };

  FarmApp.openPostDetail = async function (id) {
    try {
      var res = await api("/api/posts/" + id);
      var p = res.data;
      var canManage = STATE.user.role === "admin" || STATE.user.id === p.user_id;
      var body =
        '<div class="post-detail">' +
        '<div class="post-detail-meta"><span class="badge badge-green">' + escapeHtml(p.category) + '</span>' +
        '<span>' + escapeHtml(p.author_name) + '</span><span>' + p.created_at + '</span><span>조회 ' + p.views + '</span></div>' +
        '<h3>' + escapeHtml(p.title) + '</h3>' +
        (p.image ? '<img src="/static/' + p.image + '" class="post-detail-img">' : '') +
        '<p class="post-detail-content">' + escapeHtml(p.content || "").replace(/\n/g, "<br>") + '</p>' +
        (canManage ? '<button class="btn btn-danger btn-sm" onclick="FarmApp.deletePost(' + p.id + ')">삭제</button>' : '') +
        '</div>';
      showPostDetailModal(body);
    } catch (err) { toast(err.message); }
  };

  function showPostDetailModal(bodyHtml) {
    var modal = $("#postDetailModal");
    if (!modal) return;
    $(".modal-body", modal).innerHTML = bodyHtml;
    modal.classList.add("open");
    icons();
  }

  FarmApp.deletePost = async function (id) {
    if (!confirm("이 게시글을 삭제하시겠습니까?")) return;
    await api("/api/posts/" + id, { method: "DELETE" });
    toast("게시글이 삭제되었습니다.");
    var modal = $("#postDetailModal");
    if (modal) modal.classList.remove("open");
    renderCommunity();
  };

  function bindCommunityFilters() {
    var tabs = $all(".board-tab");
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        tabs.forEach(function (t) { t.classList.remove("active"); });
        tab.classList.add("active");
        STATE.postFilter.category = tab.getAttribute("data-category");
        STATE.postFilter.page = 1;
        renderCommunity();
      });
    });
    var searchBtn = $("#postSearchBtn");
    var searchInput = $("#postSearchInput");
    if (searchBtn) {
      searchBtn.addEventListener("click", function () {
        STATE.postFilter.q = searchInput.value.trim();
        STATE.postFilter.page = 1;
        renderCommunity();
      });
    }
    if (searchInput) {
      searchInput.addEventListener("keydown", function (e) {
        if (e.key === "Enter") { e.preventDefault(); searchBtn.click(); }
      });
    }
  }

  document.addEventListener("submit", async function (e) {
    if (e.target.id === "postForm") {
      e.preventDefault();
      var fd = new FormData();
      fd.append("category", $("#postCategory").value);
      fd.append("title", $("#postTitle").value);
      fd.append("content", $("#postContent").value);
      var pinEl = $("#postIsPinned");
      if (pinEl) fd.append("is_pinned", pinEl.checked ? "true" : "false");
      var imgFile = $("#postImage").files[0];
      if (imgFile) fd.append("image", imgFile);
      try {
        await api("/api/posts", { method: "POST", body: fd });
        $("#postModal").classList.remove("open");
        toast("게시글이 등록되었습니다.");
        renderCommunity();
      } catch (err) { toast(err.message); }
    }
  });

  // ---------- 농업 링크 모음 ----------
  async function renderLinks() {
    var res = await api("/api/links");
    STATE.links = res.data;
    var el = $("#linksDirectory");
    if (!el) return;
    if (!STATE.links.length) { el.innerHTML = '<div class="empty-msg">등록된 링크가 없습니다.</div>'; return; }
    var groups = {};
    STATE.links.forEach(function (l) {
      groups[l.category] = groups[l.category] || [];
      groups[l.category].push(l);
    });
    el.innerHTML = Object.keys(groups).map(function (cat) {
      return '<div class="link-group"><h3>' + escapeHtml(cat) + '</h3><div class="link-cards">' +
        groups[cat].map(function (l) {
          return '<a class="link-card" href="' + escapeHtml(l.url) + '" target="_blank" rel="noopener">' +
            '<div class="link-card-title"><i data-lucide="external-link"></i>' + escapeHtml(l.title) + '</div>' +
            (l.description ? '<p>' + escapeHtml(l.description) + '</p>' : '') + '</a>';
        }).join("") + '</div></div>';
    }).join("");
    icons();
  }


  // ---------- 출하 관리 ----------
  async function renderShipments() {
    var res = await api("/api/shipments");
    STATE.shipments = res.data;
    var tbody = $("#shipmentTableBody");
    tbody.innerHTML = STATE.shipments.length ? STATE.shipments.map(function (s) {
      var statusBadge = s.status === "정산완료" ? "badge-green" : s.status === "출하완료" ? "badge-blue" : "badge-amber";
      return '<tr><td>' + escapeHtml(s.crop_name || "-") + '</td><td>' + escapeHtml(s.buyer || "-") + '</td>' +
        '<td>' + s.quantity + ' ' + escapeHtml(s.unit || "") + '</td><td>' + fmtNumber(s.unit_price) + '원</td>' +
        '<td>' + fmtNumber(s.total_price) + '원</td><td>' + (s.shipment_date || "-") + '</td>' +
        '<td><span class="badge ' + statusBadge + '">' + escapeHtml(s.status) + '</span></td>' +
        '<td class="row-actions"><button class="btn btn-outline btn-sm" onclick="FarmApp.editShipment(' + s.id + ')"><i data-lucide="pencil"></i></button>' +
        '<button class="btn btn-danger btn-sm" onclick="FarmApp.deleteShipment(' + s.id + ')"><i data-lucide="trash-2"></i></button></td></tr>';
    }).join("") : '<tr><td colspan="8" class="empty-msg">등록된 출하 내역이 없습니다.</td></tr>';
    icons();
  }

  FarmApp.editShipment = function (id) {
    var s = STATE.shipments.find(function (x) { return x.id === id; });
    if (!s) return;
    openModal("shipmentModal", false);
    populateSelectOptions();
    $("#shipmentModalTitle").textContent = "출하 정보 수정";
    $("#shipmentId").value = s.id;
    $("#shipmentCropId").value = s.crop_id || "";
    $("#shipmentBuyer").value = s.buyer || "";
    $("#shipmentQuantity").value = s.quantity || "";
    $("#shipmentUnit").value = s.unit || "";
    $("#shipmentUnitPrice").value = s.unit_price || "";
    $("#shipmentDate").value = s.shipment_date || "";
    $("#shipmentStatus").value = s.status || "예정";
    $("#shipmentMemo").value = s.memo || "";
  };

  FarmApp.deleteShipment = async function (id) {
    if (!confirm("이 출하 내역을 삭제하시겠습니까?")) return;
    await api("/api/shipments/" + id, { method: "DELETE" });
    toast("출하 내역이 삭제되었습니다.");
    renderShipments();
  };

  document.addEventListener("submit", async function (e) {
    if (e.target.id === "shipmentForm") {
      e.preventDefault();
      var id = $("#shipmentId").value;
      var body = {
        crop_id: $("#shipmentCropId").value || null, buyer: $("#shipmentBuyer").value,
        quantity: $("#shipmentQuantity").value, unit: $("#shipmentUnit").value,
        unit_price: $("#shipmentUnitPrice").value, shipment_date: $("#shipmentDate").value,
        status: $("#shipmentStatus").value, memo: $("#shipmentMemo").value
      };
      try {
        if (id) await api("/api/shipments/" + id, { method: "PUT", body: body });
        else await api("/api/shipments", { method: "POST", body: body });
        $("#shipmentModal").classList.remove("open");
        toast("출하 정보가 저장되었습니다.");
        renderShipments();
        renderDashboard();
      } catch (err) { toast(err.message); }
    }
  });

  // ---------- 농작업 안전 ----------
  async function renderSafety() {
    var res = await api("/api/safety");
    STATE.safety = res.data;
    var list = $("#safetyList");
    list.innerHTML = STATE.safety.map(function (s) {
      return '<div class="item-card"><div class="item-card-body">' +
        '<div class="item-card-title">' + escapeHtml(s.title) + '<span class="badge badge-amber">' + escapeHtml(s.category) + '</span></div>' +
        '<div class="item-card-meta">' + escapeHtml(s.content) + '</div></div></div>';
    }).join("");
  }

  // ---------- 사용자 관리 (관리자) ----------
  async function renderAdmin() {
    if (STATE.user.role !== "admin") return;
    var res = await api("/api/users");
    STATE.users = res.data;
    if (!STATE.plans.length) {
      try { var pr = await api("/api/plans"); STATE.plans = pr.data; } catch (e) {}
    }
    if (!STATE.grades.length) {
      try { var gr = await api("/api/grades"); STATE.grades = gr.data; } catch (e) {}
    }
    renderAdminStats();
    renderBulkGradeSelect();
    STATE.selectedUserIds = [];

    var tbody = $("#adminUserTableBody");
    tbody.innerHTML = STATE.users.map(function (u) {
      var roleOptions = ["admin", "farmer"].map(function (r) {
        return '<option value="' + r + '" ' + (r === u.role ? "selected" : "") + '>' + (r === "admin" ? "관리자" : "농민") + '</option>';
      }).join("");
      var gradeOptions = STATE.grades.map(function (g) {
        return '<option value="' + g.id + '" ' + (g.id === u.grade_id ? "selected" : "") + '>' + escapeHtml(g.name) + '</option>';
      }).join("");
      return '<tr><td><input type="checkbox" class="userRowCheckbox" value="' + u.id + '" ' + (u.id === STATE.user.id ? "disabled" : "") + '></td>' +
        '<td>' + escapeHtml(u.name) + '</td><td>' + escapeHtml(u.email) + '</td>' +
        '<td><select onchange="FarmApp.updateUserRole(' + u.id + ', this.value)" ' + (u.id === STATE.user.id ? "disabled" : "") + '>' + roleOptions + '</select></td>' +
        '<td><select onchange="FarmApp.updateUserGrade(' + u.id + ', this.value)">' + gradeOptions + '</select></td>' +
        '<td><span class="plan-badge plan-' + escapeHtml(u.plan_code || "free") + '">' + escapeHtml(u.plan_name || "무료") + (u.is_waived ? ' <i data-lucide="badge-check" title="면제"></i>' : '') + '</span>' +
        '<div style="margin-top:4px; display:flex; gap:4px;"><button class="btn btn-outline btn-sm" onclick="FarmApp.openUserPlanModal(' + u.id + ')">변경</button>' +
        '<button class="btn btn-outline btn-sm" onclick="FarmApp.toggleWaive(' + u.id + ', ' + (!u.is_waived) + ')">' + (u.is_waived ? "면제해제" : "면제") + '</button></div></td>' +
        '<td>' + escapeHtml(u.farm_name || "-") + '</td><td>' + escapeHtml(u.region || "-") + '</td>' +
        '<td><span class="badge ' + (u.is_active_user ? "badge-green" : "badge-red") + '">' + (u.is_active_user ? "활성" : "비활성") + '</span></td>' +
        '<td class="row-actions">' +
        '<button class="btn btn-outline btn-sm" onclick="FarmApp.toggleUserActive(' + u.id + ', ' + (!u.is_active_user) + ')" ' + (u.id === STATE.user.id ? "disabled" : "") + '>' + (u.is_active_user ? "비활성화" : "활성화") + '</button>' +
        '<button class="btn btn-danger btn-sm" onclick="FarmApp.deleteUser(' + u.id + ')" ' + (u.id === STATE.user.id ? "disabled" : "") + '><i data-lucide="trash-2"></i></button>' +
        '</td></tr>';
    }).join("");
    icons();
    renderAdminActivityLogs();
    bindUserCheckboxes();
  }

  async function renderAdminStats() {
    var box = $("#adminDashboardStats");
    if (!box) return;
    try {
      var res = await api("/api/admin/stats");
      var s = res.data;
      box.innerHTML =
        '<div class="stat-card"><i data-lucide="users"></i><div><h3>' + s.total_users + '</h3><p>전체 회원</p></div></div>' +
        '<div class="stat-card"><i data-lucide="user-check"></i><div><h3>' + s.active_users + '</h3><p>활성 회원</p></div></div>' +
        '<div class="stat-card"><i data-lucide="credit-card"></i><div><h3>' + s.active_subscriptions + '</h3><p>활성 구독</p></div></div>' +
        '<div class="stat-card"><i data-lucide="badge-check"></i><div><h3>' + s.waived_subscriptions + '</h3><p>요금제 면제</p></div></div>' +
        '<div class="stat-card"><i data-lucide="message-square"></i><div><h3>' + s.total_posts + '</h3><p>게시글 수</p></div></div>' +
        '<div class="stat-card"><i data-lucide="scan-eye"></i><div><h3>' + s.total_diagnoses + '</h3><p>AI 진단 건수</p></div></div>';
      icons();
    } catch (err) {}
  }

  function renderBulkGradeSelect() {
    var sel = $("#bulkGradeSelect");
    if (!sel) return;
    sel.innerHTML = STATE.grades.map(function (g) {
      return '<option value="' + g.id + '">' + escapeHtml(g.name) + '</option>';
    }).join("");
  }

  function bindUserCheckboxes() {
    var selectAll = $("#userSelectAll");
    var headerCb = $("#userHeaderCheckbox");
    function syncSelected() {
      STATE.selectedUserIds = $all(".userRowCheckbox").filter(function (c) { return c.checked; }).map(function (c) { return parseInt(c.value, 10); });
    }
    $all(".userRowCheckbox").forEach(function (cb) {
      cb.addEventListener("change", syncSelected);
    });
    [selectAll, headerCb].forEach(function (master) {
      if (!master) return;
      master.addEventListener("change", function () {
        $all(".userRowCheckbox").forEach(function (cb) { if (!cb.disabled) cb.checked = master.checked; });
        syncSelected();
      });
    });
  }

  async function bulkUserAction(action, extra) {
    if (!STATE.selectedUserIds.length) { toast("대상 사용자를 선택해주세요."); return; }
    var body = Object.assign({ user_ids: STATE.selectedUserIds, action: action }, extra || {});
    try {
      var res = await api("/api/users/bulk", { method: "POST", body: body });
      toast(res.count + "명 처리되었습니다.");
      renderAdmin();
    } catch (err) { toast(err.message); }
  }

  function bindBulkButtons() {
    var setGradeBtn = $("#bulkSetGradeBtn");
    if (setGradeBtn) setGradeBtn.addEventListener("click", function () {
      var gradeId = $("#bulkGradeSelect").value;
      bulkUserAction("set_grade", { grade_id: gradeId ? parseInt(gradeId, 10) : null });
    });
    var activateBtn = $("#bulkActivateBtn");
    if (activateBtn) activateBtn.addEventListener("click", function () { bulkUserAction("activate"); });
    var deactivateBtn = $("#bulkDeactivateBtn");
    if (deactivateBtn) deactivateBtn.addEventListener("click", function () { bulkUserAction("deactivate"); });
  }

  FarmApp.updateUserGrade = async function (id, gradeId) {
    try {
      await api("/api/users/" + id, { method: "PUT", body: { grade_id: gradeId ? parseInt(gradeId, 10) : null } });
      toast("등급이 변경되었습니다.");
      renderAdmin();
    } catch (err) { toast(err.message); }
  };

  FarmApp.toggleWaive = async function (id, waive) {
    try {
      await api("/api/users/" + id + "/waive", { method: "POST", body: { waive: waive } });
      toast(waive ? "요금제 이용료가 면제되었습니다." : "면제가 해제되었습니다.");
      renderAdmin();
    } catch (err) { toast(err.message); }
  };

  async function renderAdminActivityLogs() {
    try {
      var res = await api("/api/admin/activity-logs");
      STATE.activityLogs = res.data;
      var list = $("#adminActivityList");
      if (!list) return;
      list.innerHTML = STATE.activityLogs.length ? STATE.activityLogs.map(function (l) {
        return '<div class="timeline-item"><div class="timeline-body">' +
          '<h4>' + escapeHtml(l.action) + '</h4>' +
          '<p>' + escapeHtml(l.admin_name) + (l.target_user_name ? " → " + escapeHtml(l.target_user_name) : "") +
          (l.detail ? " · " + escapeHtml(l.detail) : "") + '</p>' +
          '<small class="muted">' + l.created_at + '</small></div></div>';
      }).join("") : '<div class="empty-msg">활동 기록이 없습니다.</div>';
    } catch (err) {}
  }

  FarmApp.openUserPlanModal = function (id) {
    var u = STATE.users.find(function (x) { return x.id === id; });
    if (!u) return;
    var select = $("#userPlanPlanId");
    select.innerHTML = STATE.plans.map(function (p) {
      return '<option value="' + p.id + '">' + escapeHtml(p.name) + '</option>';
    }).join("");
    openModal("userPlanModal", false);
    $("#userPlanModalTitle").textContent = escapeHtml(u.name) + "님 요금제 변경";
    $("#userPlanUserId").value = u.id;
    var currentPlan = STATE.plans.find(function (p) { return p.code === u.plan_code; });
    if (currentPlan) select.value = currentPlan.id;
    $("#userPlanBillingCycle").value = u.billing_cycle || "monthly";
    $("#userPlanStatus").value = u.subscription_status || "active";
    $("#userPlanExpiryDate").value = u.subscription_expiry || "";
    $("#userPlanIsWaived").checked = !!u.is_waived;
  };

  document.addEventListener("submit", async function (e) {
    if (e.target.id === "userPlanForm") {
      e.preventDefault();
      var uid = $("#userPlanUserId").value;
      var body = {
        plan_id: $("#userPlanPlanId").value,
        billing_cycle: $("#userPlanBillingCycle").value,
        status: $("#userPlanStatus").value,
        expiry_date: $("#userPlanExpiryDate").value || null,
        is_waived: $("#userPlanIsWaived").checked
      };
      try {
        await api("/api/users/" + uid + "/plan", { method: "PUT", body: body });
        $("#userPlanModal").classList.remove("open");
        toast("사용자 요금제가 변경되었습니다.");
        renderAdmin();
      } catch (err) { toast(err.message); }
    }
  });

  FarmApp.updateUserRole = async function (id, role) {
    try {
      await api("/api/users/" + id, { method: "PUT", body: { role: role } });
      toast("권한이 변경되었습니다.");
      renderAdmin();
    } catch (err) { toast(err.message); }
  };

  FarmApp.toggleUserActive = async function (id, active) {
    try {
      await api("/api/users/" + id, { method: "PUT", body: { is_active_user: active } });
      toast(active ? "계정이 활성화되었습니다." : "계정이 비활성화되었습니다.");
      renderAdmin();
    } catch (err) { toast(err.message); }
  };

  FarmApp.deleteUser = async function (id) {
    if (!confirm("이 사용자를 삭제하시겠습니까?")) return;
    try {
      await api("/api/users/" + id, { method: "DELETE" });
      toast("사용자가 삭제되었습니다.");
      renderAdmin();
    } catch (err) { toast(err.message); }
  };

  // ---------- 요금제 (일반 사용자) ----------
  function bindBillingToggle() {
    var toggle = $("#billingToggle");
    if (!toggle) return;
    $all(".toggle-btn", toggle).forEach(function (btn) {
      btn.addEventListener("click", function () {
        $all(".toggle-btn", toggle).forEach(function (b) { b.classList.remove("active"); });
        btn.classList.add("active");
        STATE.billingCycle = btn.getAttribute("data-cycle");
        renderPricingGrid();
      });
    });
  }

  async function renderPricing() {
    var res = await api("/api/plans");
    STATE.plans = res.data;
    try {
      var subRes = await api("/api/subscriptions/me");
      STATE.mySubscription = subRes.data;
    } catch (e) {}
    STATE.appliedPromo = null;
    var statusEl = $("#promoStatus");
    if (statusEl) statusEl.textContent = "";
    var promoInput = $("#promoCodeInput");
    if (promoInput) promoInput.value = "";
    renderPricingGrid();
  }

  function renderPricingGrid() {
    var grid = $("#pricingGrid");
    if (!grid) return;
    var cycle = STATE.billingCycle;
    var currentCode = STATE.mySubscription ? STATE.mySubscription.plan_code : "free";
    var gradeDiscount = (STATE.user && STATE.user.grade_discount) || 0;
    var promoDiscount = STATE.appliedPromo ? STATE.appliedPromo.discount_percent : 0;
    var totalDiscount = Math.min(gradeDiscount + promoDiscount, 100);
    grid.innerHTML = STATE.plans.filter(function (p) { return p.is_active; }).map(function (p) {
      var price = cycle === "annual" ? p.price_annual : p.price_monthly;
      var discountedPrice = totalDiscount ? Math.round(price * (100 - totalDiscount) / 100) : price;
      var isCurrent = p.code === currentCode;
      var featureItems = (p.features || []).map(function (f) {
        return '<li><i data-lucide="check-circle-2"></i>' + escapeHtml(f) + '</li>';
      }).join("");
      return '<div class="pricing-card ' + (isCurrent ? "current" : "") + '">' +
        (isCurrent ? '<span class="pricing-card-badge">현재 요금제</span>' : '') +
        '<h3>' + escapeHtml(p.name) + '</h3>' +
        '<div class="price">' +
        (price && totalDiscount ? '<span class="price-original">' + fmtNumber(price) + '원</span> ' : '') +
        (discountedPrice ? fmtNumber(discountedPrice) + '원' : '무료') +
        (price ? '<small> / ' + (cycle === "annual" ? "년" : "월") + '</small>' : '') +
        (price && totalDiscount ? '<span class="badge badge-green discount-badge">' + totalDiscount + '% 할인</span>' : '') +
        '</div>' +
        '<ul class="feature-list">' + featureItems + '</ul>' +
        (isCurrent ? '<button class="btn btn-outline btn-block" disabled>현재 이용중</button>' :
          '<button class="btn btn-primary btn-block" onclick="FarmApp.upgradePlan(' + p.id + ')">' +
          (currentCode === "free" || comparePlanRank(p.code, currentCode) > 0 ? "업그레이드" : "다운그레이드") + '</button>') +
        '</div>';
    }).join("");
    icons();
  }

  function bindPromoApply() {
    var btn = $("#promoApplyBtn");
    if (!btn) return;
    btn.addEventListener("click", async function () {
      var code = $("#promoCodeInput").value.trim();
      var statusEl = $("#promoStatus");
      if (!code) { STATE.appliedPromo = null; statusEl.textContent = ""; renderPricingGrid(); return; }
      try {
        var res = await api("/api/promo-codes/validate", { method: "POST", body: { code: code } });
        STATE.appliedPromo = res.data;
        statusEl.textContent = "코드 적용됨: " + res.data.discount_percent + "% 할인";
        statusEl.className = "promo-status success";
        renderPricingGrid();
      } catch (err) {
        STATE.appliedPromo = null;
        statusEl.textContent = err.message;
        statusEl.className = "promo-status error";
        renderPricingGrid();
      }
    });
  }

  var PLAN_RANK = { free: 0, starter: 1, pro: 2, enterprise: 3 };
  function comparePlanRank(a, b) {
    return (PLAN_RANK[a] || 0) - (PLAN_RANK[b] || 0);
  }

  FarmApp.upgradePlan = async function (planId) {
    if (!confirm("선택한 요금제로 변경하시겠습니까?")) return;
    try {
      await api("/api/subscriptions/upgrade", {
        method: "POST",
        body: {
          plan_id: planId, billing_cycle: STATE.billingCycle,
          promo_code: STATE.appliedPromo ? STATE.appliedPromo.code : null
        }
      });
      toast("요금제가 변경되었습니다.");
      renderPricing();
    } catch (err) { toast(err.message); }
  };

  // ---------- 요금제 관리 (관리자) ----------
  async function renderPlanManagement() {
    if (STATE.user.role !== "admin") return;
    var res = await api("/api/plans");
    STATE.plans = res.data;
    var tbody = $("#planTableBody");
    tbody.innerHTML = STATE.plans.length ? STATE.plans.map(function (p) {
      return '<tr><td>' + p.display_order + '</td><td>' + escapeHtml(p.code) + '</td><td>' + escapeHtml(p.name) + '</td>' +
        '<td>' + fmtNumber(p.price_monthly) + '원</td><td>' + fmtNumber(p.price_annual) + '원</td>' +
        '<td>' + (p.features || []).map(escapeHtml).join(", ") + '</td>' +
        '<td><span class="badge ' + (p.is_active ? "badge-green" : "badge-red") + '">' + (p.is_active ? "활성" : "비활성") + '</span></td>' +
        '<td class="row-actions">' +
        '<button class="btn btn-outline btn-sm" onclick="FarmApp.editPlan(' + p.id + ')"><i data-lucide="pencil"></i></button>' +
        '<button class="btn btn-outline btn-sm" onclick="FarmApp.togglePlanActive(' + p.id + ', ' + (!p.is_active) + ')">' + (p.is_active ? "비활성화" : "활성화") + '</button>' +
        (p.code !== "free" ? '<button class="btn btn-danger btn-sm" onclick="FarmApp.deletePlan(' + p.id + ')"><i data-lucide="trash-2"></i></button>' : '') +
        '</td></tr>';
    }).join("") : '<tr><td colspan="8" class="empty-msg">등록된 요금제가 없습니다.</td></tr>';
    icons();
  }

  FarmApp.editPlan = function (id) {
    var p = STATE.plans.find(function (x) { return x.id === id; });
    if (!p) return;
    openModal("planModal", false);
    $("#planModalTitle").textContent = "요금제 수정";
    $("#planId").value = p.id;
    $("#planCode").value = p.code || "";
    $("#planName").value = p.name || "";
    $("#planPriceMonthly").value = p.price_monthly || 0;
    $("#planPriceAnnual").value = p.price_annual || 0;
    $("#planDisplayOrder").value = p.display_order || 0;
    $("#planFeatures").value = (p.features || []).join("\n");
    $("#planIsActive").checked = !!p.is_active;
  };

  FarmApp.togglePlanActive = async function (id, active) {
    try {
      await api("/api/plans/" + id, { method: "PUT", body: { is_active: active } });
      toast(active ? "요금제가 활성화되었습니다." : "요금제가 비활성화되었습니다.");
      renderPlanManagement();
    } catch (err) { toast(err.message); }
  };

  FarmApp.deletePlan = async function (id) {
    if (!confirm("이 요금제를 삭제하시겠습니까? 해당 요금제를 이용중인 사용자는 무료 요금제 기준으로 표시됩니다.")) return;
    try {
      await api("/api/plans/" + id, { method: "DELETE" });
      toast("요금제가 삭제되었습니다.");
      renderPlanManagement();
    } catch (err) { toast(err.message); }
  };

  document.addEventListener("submit", async function (e) {
    if (e.target.id === "planForm") {
      e.preventDefault();
      var id = $("#planId").value;
      var body = {
        code: $("#planCode").value.trim(),
        name: $("#planName").value.trim(),
        price_monthly: $("#planPriceMonthly").value,
        price_annual: $("#planPriceAnnual").value,
        display_order: $("#planDisplayOrder").value,
        features: $("#planFeatures").value.split("\n").map(function (s) { return s.trim(); }).filter(Boolean),
        is_active: $("#planIsActive").checked
      };
      try {
        if (id) await api("/api/plans/" + id, { method: "PUT", body: body });
        else await api("/api/plans", { method: "POST", body: body });
        $("#planModal").classList.remove("open");
        toast("요금제가 저장되었습니다.");
        renderPlanManagement();
      } catch (err) { toast(err.message); }
    }
  });

  // ---------- 등급 관리 (관리자) ----------
  async function renderGradeManagement() {
    if (STATE.user.role !== "admin") return;
    var res = await api("/api/grades");
    STATE.grades = res.data;
    var tbody = $("#gradeTableBody");
    tbody.innerHTML = STATE.grades.length ? STATE.grades.map(function (g) {
      return '<tr><td>' + g.display_order + '</td><td>' + escapeHtml(g.code) + '</td>' +
        '<td><span class="grade-badge" style="background:' + escapeHtml(g.color) + '">' + escapeHtml(g.name) + '</span></td>' +
        '<td>' + g.discount_percent + '%</td><td>' + fmtNumber(g.min_spend) + '원</td>' +
        '<td>' + escapeHtml(g.description || "-") + '</td>' +
        '<td class="row-actions"><button class="btn btn-outline btn-sm" onclick="FarmApp.editGrade(' + g.id + ')"><i data-lucide="pencil"></i></button>' +
        '<button class="btn btn-danger btn-sm" onclick="FarmApp.deleteGrade(' + g.id + ')"><i data-lucide="trash-2"></i></button></td></tr>';
    }).join("") : '<tr><td colspan="7" class="empty-msg">등록된 등급이 없습니다.</td></tr>';
    icons();
  }

  FarmApp.editGrade = function (id) {
    var g = STATE.grades.find(function (x) { return x.id === id; });
    if (!g) return;
    openModal("gradeModal", false);
    $("#gradeModalTitle").textContent = "등급 수정";
    $("#gradeId").value = g.id;
    $("#gradeCode").value = g.code || "";
    $("#gradeName").value = g.name || "";
    $("#gradeDiscountPercent").value = g.discount_percent || 0;
    $("#gradeMinSpend").value = g.min_spend || 0;
    $("#gradeColor").value = g.color || "#4caf7d";
    $("#gradeDisplayOrder").value = g.display_order || 0;
    $("#gradeDescription").value = g.description || "";
  };

  FarmApp.deleteGrade = async function (id) {
    if (!confirm("이 등급을 삭제하시겠습니까? 해당 등급의 사용자는 등급이 해제됩니다.")) return;
    try {
      await api("/api/grades/" + id, { method: "DELETE" });
      toast("등급이 삭제되었습니다.");
      renderGradeManagement();
    } catch (err) { toast(err.message); }
  };

  document.addEventListener("submit", async function (e) {
    if (e.target.id === "gradeForm") {
      e.preventDefault();
      var id = $("#gradeId").value;
      var body = {
        code: $("#gradeCode").value.trim(), name: $("#gradeName").value.trim(),
        discount_percent: $("#gradeDiscountPercent").value, min_spend: $("#gradeMinSpend").value,
        color: $("#gradeColor").value, display_order: $("#gradeDisplayOrder").value,
        description: $("#gradeDescription").value
      };
      try {
        if (id) await api("/api/grades/" + id, { method: "PUT", body: body });
        else await api("/api/grades", { method: "POST", body: body });
        $("#gradeModal").classList.remove("open");
        toast("등급이 저장되었습니다.");
        renderGradeManagement();
      } catch (err) { toast(err.message); }
    }
  });

  // ---------- 프로모션 코드 관리 (관리자) ----------
  async function renderPromoManagement() {
    if (STATE.user.role !== "admin") return;
    var res = await api("/api/admin/promo-codes");
    STATE.promoCodes = res.data;
    var tbody = $("#promoTableBody");
    tbody.innerHTML = STATE.promoCodes.length ? STATE.promoCodes.map(function (p) {
      return '<tr><td>' + escapeHtml(p.code) + '</td><td>' + p.discount_percent + '%</td>' +
        '<td>' + escapeHtml(p.description || "-") + '</td>' +
        '<td>' + p.used_count + ' / ' + (p.max_uses || "무제한") + '</td>' +
        '<td>' + (p.expiry_date || "-") + '</td>' +
        '<td><span class="badge ' + (p.is_active ? "badge-green" : "badge-red") + '">' + (p.is_active ? "활성" : "비활성") + '</span></td>' +
        '<td class="row-actions"><button class="btn btn-outline btn-sm" onclick="FarmApp.editPromo(' + p.id + ')"><i data-lucide="pencil"></i></button>' +
        '<button class="btn btn-outline btn-sm" onclick="FarmApp.togglePromoActive(' + p.id + ', ' + (!p.is_active) + ')">' + (p.is_active ? "비활성화" : "활성화") + '</button>' +
        '<button class="btn btn-danger btn-sm" onclick="FarmApp.deletePromo(' + p.id + ')"><i data-lucide="trash-2"></i></button></td></tr>';
    }).join("") : '<tr><td colspan="7" class="empty-msg">등록된 프로모션 코드가 없습니다.</td></tr>';
    icons();
  }

  FarmApp.editPromo = function (id) {
    var p = STATE.promoCodes.find(function (x) { return x.id === id; });
    if (!p) return;
    openModal("promoModal", false);
    $("#promoModalTitle").textContent = "프로모션 코드 수정";
    $("#promoId").value = p.id;
    $("#promoCode").value = p.code || "";
    $("#promoDiscountPercent").value = p.discount_percent || 0;
    $("#promoMaxUses").value = p.max_uses || 0;
    $("#promoExpiryDate").value = p.expiry_date || "";
    $("#promoDescription").value = p.description || "";
    $("#promoIsActive").checked = !!p.is_active;
  };

  FarmApp.togglePromoActive = async function (id, active) {
    try {
      await api("/api/admin/promo-codes/" + id, { method: "PUT", body: { is_active: active } });
      toast(active ? "코드가 활성화되었습니다." : "코드가 비활성화되었습니다.");
      renderPromoManagement();
    } catch (err) { toast(err.message); }
  };

  FarmApp.deletePromo = async function (id) {
    if (!confirm("이 프로모션 코드를 삭제하시겠습니까?")) return;
    try {
      await api("/api/admin/promo-codes/" + id, { method: "DELETE" });
      toast("코드가 삭제되었습니다.");
      renderPromoManagement();
    } catch (err) { toast(err.message); }
  };

  document.addEventListener("submit", async function (e) {
    if (e.target.id === "promoForm") {
      e.preventDefault();
      var id = $("#promoId").value;
      var body = {
        code: $("#promoCode").value.trim().toUpperCase(),
        discount_percent: $("#promoDiscountPercent").value,
        max_uses: $("#promoMaxUses").value,
        expiry_date: $("#promoExpiryDate").value || null,
        description: $("#promoDescription").value,
        is_active: $("#promoIsActive").checked
      };
      try {
        if (id) await api("/api/admin/promo-codes/" + id, { method: "PUT", body: body });
        else await api("/api/admin/promo-codes", { method: "POST", body: body });
        $("#promoModal").classList.remove("open");
        toast("프로모션 코드가 저장되었습니다.");
        renderPromoManagement();
      } catch (err) { toast(err.message); }
    }
  });

  // ---------- 농업 링크 관리 (관리자) ----------
  async function renderLinkManagement() {
    if (STATE.user.role !== "admin") return;
    var res = await api("/api/links");
    STATE.links = res.data;
    var tbody = $("#linkAdminTableBody");
    tbody.innerHTML = STATE.links.length ? STATE.links.map(function (l) {
      return '<tr><td>' + escapeHtml(l.category) + '</td><td>' + escapeHtml(l.title) + '</td>' +
        '<td><a href="' + escapeHtml(l.url) + '" target="_blank" rel="noopener">' + escapeHtml(l.url) + '</a></td>' +
        '<td>' + escapeHtml(l.description || "-") + '</td><td>' + l.display_order + '</td>' +
        '<td class="row-actions"><button class="btn btn-outline btn-sm" onclick="FarmApp.editLink(' + l.id + ')"><i data-lucide="pencil"></i></button>' +
        '<button class="btn btn-danger btn-sm" onclick="FarmApp.deleteLink(' + l.id + ')"><i data-lucide="trash-2"></i></button></td></tr>';
    }).join("") : '<tr><td colspan="6" class="empty-msg">등록된 링크가 없습니다.</td></tr>';
    icons();
  }

  FarmApp.editLink = function (id) {
    var l = STATE.links.find(function (x) { return x.id === id; });
    if (!l) return;
    openModal("linkModal", false);
    $("#linkModalTitle").textContent = "링크 수정";
    $("#linkId").value = l.id;
    $("#linkTitle").value = l.title || "";
    $("#linkUrl").value = l.url || "";
    $("#linkCategory").value = l.category || "공공기관";
    $("#linkDescription").value = l.description || "";
    $("#linkDisplayOrder").value = l.display_order || 0;
  };

  FarmApp.deleteLink = async function (id) {
    if (!confirm("이 링크를 삭제하시겠습니까?")) return;
    try {
      await api("/api/links/" + id, { method: "DELETE" });
      toast("링크가 삭제되었습니다.");
      renderLinkManagement();
    } catch (err) { toast(err.message); }
  };

  document.addEventListener("submit", async function (e) {
    if (e.target.id === "linkForm") {
      e.preventDefault();
      var id = $("#linkId").value;
      var body = {
        title: $("#linkTitle").value.trim(), url: $("#linkUrl").value.trim(),
        category: $("#linkCategory").value, description: $("#linkDescription").value,
        display_order: $("#linkDisplayOrder").value
      };
      try {
        if (id) await api("/api/links/" + id, { method: "PUT", body: body });
        else await api("/api/links", { method: "POST", body: body });
        $("#linkModal").classList.remove("open");
        toast("링크가 저장되었습니다.");
        renderLinkManagement();
      } catch (err) { toast(err.message); }
    }
  });

  // -------------------------------------------------------------
  // 초기화
  // -------------------------------------------------------------
  async function initAppPage() {
    icons();
    var me = await api("/api/me").catch(function () { return null; });
    if (!me || !me.ok) { window.location.href = "/"; return; }
    STATE.user = me.user;

    var sideGradeEl = $("#sideUserGrade");
    if (sideGradeEl) {
      sideGradeEl.textContent = STATE.user.grade_name || "일반회원";
      sideGradeEl.style.background = STATE.user.grade_color || "#8a9a8a";
    }

    if (STATE.user.role === "admin") {
      $all(".admin-only").forEach(function (el) { el.style.display = ""; });
      $all(".user-only").forEach(function (el) { el.style.display = "none"; });
      $all(".admin-only-option").forEach(function (el) { el.style.display = ""; });
    }

    bindNav();
    bindBillingToggle();
    bindCommunityFilters();
    bindBulkButtons();
    bindPromoApply();

    $("#weatherSearchBtn").addEventListener("click", function () { renderWeather($("#weatherRegionInput").value); });
    var pesticideInput = $("#pesticideSearch");
    var pesticideTimer;
    pesticideInput.addEventListener("input", function () {
      clearTimeout(pesticideTimer);
      pesticideTimer = setTimeout(function () { renderPesticides(pesticideInput.value); }, 300);
    });

    // 초기 참조 데이터 로드 (셀렉트박스용)
    try {
      var cropsRes = await api("/api/crops");
      STATE.crops = cropsRes.data;
      populateSelectOptions();
    } catch (e) {}
    try {
      var gradesRes = await api("/api/grades");
      STATE.grades = gradesRes.data;
    } catch (e) {}

    navigateTo("dashboard");

    // PWA 서비스워커 등록
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/service-worker.js").catch(function () {});
    }
  }

  // -------------------------------------------------------------
  // 진입점
  // -------------------------------------------------------------
  document.addEventListener("DOMContentLoaded", function () {
    if ($("#loginForm")) {
      initAuthPage();
    } else if ($("#appShell")) {
      initAppPage();
    }
  });
})();
