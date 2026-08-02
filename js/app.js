/**
 * 高考志愿填报 App — 页面导航、数据加载与渲染逻辑
 *
 * 数据分两类：
 *   1. 静态配置（provinces / score-input / preferences）— 直接从 data/*.json 加载
 *   2. 后端接口数据（recommendations / probability / schoolDetail / generatingSteps）— 通过 api 对象调用
 *
 * 认证流程：
 *   启动时检查 localStorage 中的 JWT token → 验证 → 加载用户档案预填表单
 *   未登录 → 显示登录/注册页
 *   生成方案时 → 自动保存档案到数据库
 */

(function () {
  'use strict';

  // ============================================
  // 配置
  // ============================================

  /** @type {boolean} true = 使用假数据(test_data.json)，false = 调用真实后端 API */
  var USE_MOCK = false;

  /** 后端 API 基础地址，USE_MOCK=false 时生效 */
  var API_BASE = '/api'; // 后端同源部署，直接用 /api 前缀

  // ============================================
  // 认证状态管理
  // ============================================

  var Auth = {
    token: localStorage.getItem('gaokao_token') || null,
    user: null,
    profile: null,

    setToken: function (token) {
      this.token = token;
      localStorage.setItem('gaokao_token', token);
    },

    clear: function () {
      this.token = null;
      this.user = null;
      this.profile = null;
      localStorage.removeItem('gaokao_token');
    },

    isLoggedIn: function () {
      return !!this.token;
    }
  };

  // ============================================
  // API 层
  // ============================================

  var _mockCache = null;

  function loadMock() {
    if (_mockCache) return Promise.resolve(_mockCache);
    return fetch('data/test_data.json').then(function (r) { return r.json(); }).then(function (d) {
      _mockCache = d;
      return d;
    });
  }

  function _authHeaders() {
    var headers = {};
    if (Auth.token) headers['Authorization'] = 'Bearer ' + Auth.token;
    return headers;
  }

  function apiGet(path, params) {
    var url = API_BASE + path;
    if (params) {
      var qs = new URLSearchParams(params).toString();
      url += (url.indexOf('?') === -1 ? '?' : '&') + qs;
    }
    return fetch(url, { headers: _authHeaders() })
      .then(function (r) { return r.json(); })
      .then(function (resp) {
        if (resp.code === 0) return resp.data;
        throw new Error(resp.message || 'API 请求失败');
      });
  }

  function apiPost(path, body) {
    var headers = { 'Content-Type': 'application/json' };
    if (Auth.token) headers['Authorization'] = 'Bearer ' + Auth.token;
    return fetch(API_BASE + path, {
      method: 'POST',
      headers: headers,
      body: JSON.stringify(body)
    })
      .then(function (r) { return r.json(); })
      .then(function (resp) {
        if (resp.code === 0) return resp.data;
        throw new Error(resp.message || 'API 请求失败');
      });
  }

  function apiPut(path, body) {
    var headers = { 'Content-Type': 'application/json' };
    if (Auth.token) headers['Authorization'] = 'Bearer ' + Auth.token;
    return fetch(API_BASE + path, {
      method: 'PUT',
      headers: headers,
      body: JSON.stringify(body)
    })
      .then(function (r) { return r.json(); })
      .then(function (resp) {
        if (resp.code === 0) return resp.data;
        throw new Error(resp.message || 'API 请求失败');
      });
  }

  var api = {
    /** 获取志愿推荐方案 */
    getRecommendations: function (params) {
      if (USE_MOCK) return loadMock().then(function (d) { return d.recommendations; });
      return apiGet('/recommendations', params);
    },
    /** 获取概率预测 */
    getProbability: function (params) {
      if (USE_MOCK) return loadMock().then(function (d) { return d.probability; });
      return apiGet('/probability', params);
    },
    /** 获取院校详情 */
    getSchoolDetail: function (schoolId, params) {
      if (USE_MOCK) return loadMock().then(function (d) { return d.schoolDetail; });
      return apiGet('/school/' + encodeURIComponent(schoolId), params);
    },
    /** 获取生成步骤状态 */
    getGeneratingSteps: function () {
      if (USE_MOCK) return loadMock().then(function (d) { return d.generatingSteps; });
      return apiGet('/generating-steps');
    },
    /** 提交考生数据，调用 LLM 生成志愿方案 */
    generatePlan: function (userData) {
      return apiPost('/generate', userData);
    },
    /** 认证相关接口 */
    auth: {
      register: function (phone, password, nickname) {
        return apiPost('/auth/register', { phone: phone, password: password, nickname: nickname || null });
      },
      login: function (phone, password) {
        return apiPost('/auth/login', { phone: phone, password: password });
      },
      getMe: function () {
        return apiGet('/auth/me');
      },
      getProfile: function () {
        return apiGet('/auth/profile');
      },
      updateProfile: function (profile) {
        return apiPut('/auth/profile', profile);
      }
    }
  };

  // ============================================
  // 数据存储
  // ============================================
  var appData = {};

  // ============================================
  // 页面导航
  // ============================================
  let currentPage = null;
  const navHistory = [];

  const pageTabMap = {
    'page-home': 'home',
    'page-results': 'plan'
  };

  function syncTabBar(pageEl) {
    const tabName = pageTabMap[pageEl.id];
    if (!tabName) return;
    const tabPill = pageEl.querySelector('.tab-pill');
    if (!tabPill) return;
    tabPill.querySelectorAll('.tab-item').forEach(i => i.classList.remove('active'));
    const targetTab = tabPill.querySelector(`[data-tab="${tabName}"]`);
    if (targetTab) targetTab.classList.add('active');
  }

  function navigateTo(pageId, addToHistory = true) {
    const target = document.getElementById(pageId);
    if (!target || target === currentPage) return;

    if (currentPage && addToHistory) {
      navHistory.push(currentPage.id);
    }

    if (currentPage) {
      const oldPage = currentPage;
      oldPage.classList.remove('active');
      oldPage.classList.add('exit-left');
      setTimeout(() => oldPage.classList.remove('exit-left'), 300);
    }

    target.classList.add('active');
    target.scrollTop = 0;
    currentPage = target;
    syncTabBar(target);
  }

  function goBack() {
    if (navHistory.length === 0) return;
    const prevId = navHistory.pop();
    const target = document.getElementById(prevId);
    if (!target) return;

    if (currentPage) currentPage.classList.remove('active');

    target.classList.remove('exit-left');
    target.classList.add('active');
    target.scrollTop = 0;
    currentPage = target;
    syncTabBar(target);
  }

  // ============================================
  // 渲染：科目选择按钮
  // ============================================
  function renderSubjects() {
    const container = document.getElementById('subject-grid');
    if (!container || !appData.scoreInput) return;

    const subjects = appData.scoreInput.subjects;
    let html = '';
    for (let i = 0; i < subjects.length; i++) {
      if (i % 3 === 0) html += '<div class="subject-row">';
      const s = subjects[i];
      html += `<button class="subject-btn${s.selected ? ' selected' : ''}">${s.name}</button>`;
      if (i % 3 === 2 || i === subjects.length - 1) html += '</div>';
    }
    container.innerHTML = html;

    const maxSelect = appData.scoreInput.maxSubjects || 3;
    container.querySelectorAll('.subject-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const selectedCount = container.querySelectorAll('.subject-btn.selected').length;
        if (!btn.classList.contains('selected') && selectedCount >= maxSelect) return;
        btn.classList.toggle('selected');
      });
    });
  }

  // ============================================
  // 渲染：偏好页（院校层次 / 专业 / 策略 / 地域）
  // ============================================
  function renderPreferences() {
    const data = appData.preferences;
    if (!data) return;

    // 院校层次 chips
    const levelContainer = document.getElementById('school-level-chips');
    if (levelContainer) {
      levelContainer.innerHTML = data.schoolLevels.map(s =>
        `<button class="chip${s.selected ? ' selected' : ''}">${s.name}</button>`
      ).join('');
      bindChips(levelContainer);
    }

    // 专业方向 chips
    const majorContainer = document.getElementById('major-chips');
    if (majorContainer) {
      majorContainer.innerHTML = data.majors.map(s =>
        `<button class="chip${s.selected ? ' selected' : ''}">${s.name}</button>`
      ).join('');
      bindChips(majorContainer);
    }

    // 策略卡片（单选）
    const strategyContainer = document.getElementById('strategy-grid');
    if (strategyContainer) {
      strategyContainer.innerHTML = data.strategies.map(s =>
        `<div class="strategy-card${s.selected ? ' selected' : ''}">
          <span class="icon">${s.icon}</span>
          <span class="text">${s.name}</span>
        </div>`
      ).join('');
      strategyContainer.querySelectorAll('.strategy-card').forEach(card => {
        card.addEventListener('click', () => {
          strategyContainer.querySelectorAll('.strategy-card').forEach(c => c.classList.remove('selected'));
          card.classList.add('selected');
        });
      });
    }

    // 地域显示
    var regionDisplay = document.getElementById('region-display');
    if (regionDisplay && data.regions && data.regions.length > 0) {
      selectedRegion = data.regions[0];
      regionDisplay.textContent = selectedRegion;
    }
  }

  function bindChips(container) {
    container.querySelectorAll('.chip').forEach(chip => {
      chip.addEventListener('click', () => chip.classList.toggle('selected'));
    });
  }

  // ============================================
  // 渲染：生成中步骤
  // ============================================
  function renderGeneratingSteps() {
    const container = document.getElementById('generating-steps');
    if (!container || !appData.generatingSteps) return;

    const indicators = { done: '✓', doing: '⟳', pending: '' };
    container.innerHTML = appData.generatingSteps.map(step =>
      `<div class="step-item ${step.status}">
        <div class="step-indicator">${indicators[step.status] || ''}</div>
        <span class="step-label">${step.label}</span>
      </div>`
    ).join('');
  }

  // ============================================
  // 渲染：志愿方案页（成绩摘要 + 分段 + 推荐列表）
  // ============================================
  function renderRecommendations() {
    const data = appData.recommendations;
    if (!data) return;

    // 成绩摘要
    const scoreValue = document.getElementById('results-score-value');
    if (scoreValue) scoreValue.textContent = `${data.scoreSummary.score} ${data.scoreSummary.unit}`;

    const scoreTags = document.getElementById('results-score-tags');
    if (scoreTags) {
      scoreTags.innerHTML =
        `<span class="score-tag">${data.scoreSummary.province}</span>` +
        `<span class="score-tag">${data.scoreSummary.subjects}</span>`;
    }

    // 分段控件
    const segmentsContainer = document.getElementById('results-segments');
    if (segmentsContainer) {
      segmentsContainer.innerHTML = data.segments.map(seg =>
        `<button class="segment-item${seg.active ? ' active' : ''}" data-segment="${seg.value}">${seg.label}</button>`
      ).join('');
      bindSegments(segmentsContainer);
    }

    // 推荐卡片列表
    const listContainer = document.getElementById('recommendation-list');
    if (listContainer) {
      listContainer.innerHTML = data.list.map((r, i) =>
        `<div class="recommendation-card" data-segment="${r.segment}" data-school-index="${i}">
          <div class="card-top">
            <span class="school-name">${r.school}</span>
            <span class="badge ${r.segment}">${r.badgeText}</span>
          </div>
          <div class="major">${r.major}</div>
          <div class="reason">${r.reason}</div>
          <div class="data-tags">
            <span class="data-tag">去年位次 ${r.lastRank}</span>
            <span class="data-tag">去年均分 ${r.lastAvgScore}</span>
          </div>
        </div>`
      ).join('');

      // 绑定卡片点击 → 跳转详情页 + 加载院校详情
      listContainer.querySelectorAll('.recommendation-card').forEach(card => {
        card.addEventListener('click', () => {
          const idx = parseInt(card.getAttribute('data-school-index'), 10);
          const rec = data.list[idx];
          if (!rec) return;
          appData.currentSchool = rec;
          navigateTo('page-detail');
          loadSchoolDetail(rec);
        });
      });
    }
  }

  function bindSegments(control) {
    const page = control.closest('.page');
    control.querySelectorAll('.segment-item').forEach(item => {
      item.addEventListener('click', () => {
        control.querySelectorAll('.segment-item').forEach(i => i.classList.remove('active'));
        item.classList.add('active');
        const segment = item.getAttribute('data-segment');
        if (segment) filterCards(segment, page);
      });
    });
  }

  function filterCards(segment, page) {
    if (!page) return;
    page.querySelectorAll('.recommendation-card').forEach(card => {
      card.style.display = (segment === 'all' || card.getAttribute('data-segment') === segment) ? '' : 'none';
    });
  }

  // ============================================
  // 渲染：概率预测页
  // ============================================
  function renderProbability() {
    const data = appData.probability;
    if (!data) return;

    const scoreValue = document.getElementById('prob-score-value');
    if (scoreValue) scoreValue.textContent = `${data.scoreSummary.score} ${data.scoreSummary.unit}`;

    const scoreTags = document.getElementById('prob-score-tags');
    if (scoreTags) {
      scoreTags.innerHTML = `<span class="score-tag">${data.scoreSummary.summary}</span>`;
    }

    const segmentsContainer = document.getElementById('prob-segments');
    if (segmentsContainer) {
      segmentsContainer.innerHTML = data.segments.map(seg =>
        `<button class="segment-item${seg.active ? ' active' : ''}" data-segment="${seg.value}">${seg.label}</button>`
      ).join('');
      bindSegments(segmentsContainer);
    }

    const cardsContainer = document.getElementById('prob-cards');
    if (!cardsContainer) return;

    const p = data.preview;
    const l = data.locked;
    const u = data.upgrade;

    cardsContainer.innerHTML =
      `<div class="recommendation-card" style="gap: var(--space-md);">
        <div class="card-top">
          <span class="school-name">${p.school}</span>
          <span class="badge ${p.badgeType}">${p.badgeText}</span>
        </div>
        <div class="major" style="font-size: var(--fs-small);">${p.major}</div>
        <div class="prob-bar">
          <div class="prob-label-row">
            <span>预测录取概率</span>
            <span class="prob-percent">${p.probability}%</span>
          </div>
          <div class="prob-track">
            <div class="prob-fill" data-width="${p.probability}"></div>
          </div>
        </div>
        <div class="reason" style="font-size: var(--fs-small);">${p.reason}</div>
      </div>` +
      `<div class="locked-card">
        <div class="locked-header">
          <span class="school-name" style="font-size: var(--fs-body-lg); font-weight: 600;">${l.school}</span>
          <span class="lock-icon">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
              <rect x="3" y="7" width="10" height="7" rx="1"/>
              <path d="M5 7V5a3 3 0 016 0v2"/>
              <circle cx="8" cy="10.5" r="0.5" fill="currentColor"/>
            </svg>
          </span>
        </div>
        <div class="blurred-content">
          <div class="skeleton" style="width: 170px"></div>
          <div class="skeleton" style="width: 120px"></div>
          <div class="skeleton" style="width: 200px"></div>
        </div>
      </div>` +
      `<div class="upgrade-card" style="margin-top: var(--space-sm);">
        <span class="upgrade-icon">${u.icon}</span>
        <div class="upgrade-title">${u.title}</div>
        <div class="upgrade-desc">${u.desc}</div>
        <button class="upgrade-cta">${u.ctaText}</button>
      </div>`;

    animateProbBars(cardsContainer);
  }

  function animateProbBars(container) {
    container.querySelectorAll('.prob-fill').forEach(fill => {
      const targetWidth = fill.getAttribute('data-width');
      fill.style.width = '0%';
      setTimeout(() => { fill.style.width = targetWidth + '%'; }, 300);
    });
  }

  // ============================================
  // 加载院校详情（调用 API）
  // ============================================
  function loadSchoolDetail(rec) {
    // 显示加载状态
    var hero = document.getElementById('detail-hero');
    var dataGrid = document.getElementById('detail-data-grid');
    var aiContent = document.getElementById('detail-ai-content');
    var similar = document.getElementById('detail-similar');

    if (hero) {
      hero.innerHTML =
        '<div style="text-align:center;padding:40px 20px;">' +
        '<div style="font-size:28px;margin-bottom:12px;">' + rec.school + '</div>' +
        '<div style="font-size:14px;opacity:0.7;">' + rec.badgeText + ' · ' + rec.major + '</div>' +
        '<div style="margin-top:20px;font-size:14px;opacity:0.6;">正在生成院校详情...</div>' +
        '</div>';
    }
    if (dataGrid) dataGrid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:20px;color:var(--color-text-muted);font-size:13px;">加载中...</div>';
    if (aiContent) aiContent.innerHTML = '<span style="color:var(--color-text-muted);">AI 分析生成中...</span>';
    if (similar) similar.innerHTML = '';

    // 从推荐方案中获取考生信息
    var scoreSummary = (appData.recommendations && appData.recommendations.scoreSummary) || {};

    api.getSchoolDetail(rec.school, {
      score: scoreSummary.score,
      province: scoreSummary.province,
      subjects: scoreSummary.subjects,
      major: rec.major,
      segment: rec.segment
    })
      .then(function (data) {
        appData.schoolDetail = data;
        renderSchoolDetail();
        bindDetailActions();
      })
      .catch(function (err) {
        if (hero) {
          hero.innerHTML =
            '<div style="text-align:center;padding:40px 20px;">' +
            '<div style="font-size:28px;margin-bottom:12px;">' + rec.school + '</div>' +
            '<div style="font-size:14px;opacity:0.7;">' + rec.badgeText + ' · ' + rec.major + '</div>' +
            '<div style="margin-top:20px;font-size:13px;color:var(--color-danger);">加载失败：' + (err.message || '未知错误') + '</div>' +
            '</div>';
        }
      });
  }

  // ============================================
  // 渲染：院校详情页
  // ============================================
  function renderSchoolDetail() {
    const data = appData.schoolDetail;
    if (!data) return;

    const hero = document.getElementById('detail-hero');
    if (hero) {
      const tagsHtml = (data.tags || []).map(t => `<span class="school-tag">${t}</span>`).join('');
      const badgeHtml = data.badge
        ? `<span class="school-tag ${data.badge.type}">${data.badge.text}</span>`
        : '';
      hero.innerHTML =
        `<div class="school-name">${data.name}</div>` +
        `<div class="school-tags">${tagsHtml}${badgeHtml}</div>` +
        `<div class="school-location">${data.location}</div>`;
    }

    const dataGrid = document.getElementById('detail-data-grid');
    if (dataGrid) {
      dataGrid.innerHTML = data.admissionData.map(d => {
        const style = d.highlight ? ' style="color: var(--color-primary);"' : '';
        return `<div class="data-item">
          <div class="data-value"${style}>${d.value}</div>
          <div class="data-label">${d.label}</div>
        </div>`;
      }).join('');
    }

    const aiContent = document.getElementById('detail-ai-content');
    if (aiContent) aiContent.innerHTML = data.aiAnalysis;

    const similar = document.getElementById('detail-similar');
    if (similar) {
      similar.innerHTML = data.similarRecommendations.map(s =>
        `<div class="similar-item">
          <div class="similar-info">
            <div class="similar-name">${s.name}</div>
            <div class="similar-major">${s.major}</div>
          </div>
          <div class="similar-prob">
            <div class="prob-value">${s.probability}</div>
            <div class="prob-label">录取概率</div>
          </div>
        </div>`
      ).join('');
    }
  }

  // ============================================
  // 院校详情页操作按钮（收藏 / 加入方案）
  // ============================================
  // 使用 onclick 赋值避免重复绑定
  function bindDetailActions() {
    var favBtn = document.getElementById('detail-fav-btn');
    var addBtn = document.getElementById('detail-add-btn');

    if (favBtn) {
      // 重置为未收藏状态
      favBtn.classList.remove('favorited');
      favBtn.innerHTML =
        '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" style="margin-right: 4px;">' +
        '<path d="M8 3v10M4 7l4-4 4 4" transform="translate(0, 1)"/></svg>收藏';

      favBtn.onclick = function () {
        if (favBtn.classList.contains('favorited')) {
          favBtn.classList.remove('favorited');
          favBtn.innerHTML =
            '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" style="margin-right: 4px;">' +
            '<path d="M8 3v10M4 7l4-4 4 4" transform="translate(0, 1)"/></svg>收藏';
        } else {
          favBtn.classList.add('favorited');
          favBtn.innerHTML = '\u2713 已收藏';
        }
      };
    }

    if (addBtn) {
      addBtn.textContent = '加入方案';
      addBtn.disabled = false;
      addBtn.style.opacity = '';

      addBtn.onclick = function () {
        addBtn.textContent = '\u2713 已加入方案';
        addBtn.disabled = true;
        addBtn.style.opacity = '0.7';
        setTimeout(function () {
          addBtn.textContent = '加入方案';
          addBtn.disabled = false;
          addBtn.style.opacity = '';
        }, 2000);
      };
    }
  }

  // ============================================
  // 省份选择器
  // ============================================
  let selectedProvince = '浙江省';
  let provinceOverlay, provinceTrigger, provinceDisplay, provinceClose,
    provinceList, provinceSearch;

  // ============================================
  // 地域选择器
  // ============================================
  let selectedRegion = '不限地域';
  let regionOverlay, regionTrigger, regionDisplay, regionClose, regionList;

  // ============================================
  // Picker scroll position save/restore
  // Prevents page scroll position from shifting when picker opens/closes
  // ============================================
  var _savedScrollTop = 0;

  function _getActiveScrollTop() {
    var activePage = document.querySelector('.page.active');
    if (!activePage) return 0;
    var cw = activePage.querySelector('.content-wrapper');
    if (cw) return cw.scrollTop;
    return activePage.scrollTop || 0;
  }

  function _restoreActiveScrollTop(saved) {
    var activePage = document.querySelector('.page.active');
    if (!activePage) return;
    var cw = activePage.querySelector('.content-wrapper');
    if (cw) {
      cw.scrollTop = saved;
    } else {
      activePage.scrollTop = saved;
    }
  }

  function renderProvinceList(filter) {
    if (!provinceList || !appData.provinces) return;
    filter = (filter || '').toLowerCase().trim();
    const filtered = appData.provinces.filter(p =>
      !filter ||
      p.short.toLowerCase().indexOf(filter) !== -1 ||
      p.full.toLowerCase().indexOf(filter) !== -1
    );

    if (filtered.length === 0) {
      provinceList.innerHTML = '<div class="picker-empty">未找到匹配的省份</div>';
      return;
    }

    provinceList.innerHTML = filtered.map(p => {
      const isSelected = p.full === selectedProvince;
      return `<div class="picker-item${isSelected ? ' selected' : ''}" data-full="${p.full}" data-short="${p.short}">
        <span>${p.short}</span>
        ${isSelected
          ? '<svg class="check-icon" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 9 7 12 14 5"/></svg>'
          : ''}
      </div>`;
    }).join('');

    provinceList.querySelectorAll('.picker-item').forEach(item => {
      item.addEventListener('click', () => {
        selectedProvince = item.getAttribute('data-full');
        if (provinceDisplay) provinceDisplay.textContent = selectedProvince;
        closeProvincePicker();
      });
    });
  }

  function openProvincePicker() {
    if (!provinceOverlay) return;
    renderProvinceList('');
    if (provinceSearch) provinceSearch.value = '';
    // Save scroll position of the active page's content-wrapper to restore on close
    _savedScrollTop = _getActiveScrollTop();
    provinceOverlay.classList.add('active');
    setTimeout(() => {
      var sel = provinceList.querySelector('.picker-item.selected');
      if (sel) {
        // Only scroll within picker-list — scrollIntoView would also scroll ancestor .page containers
        var offset = sel.offsetTop - provinceList.offsetTop;
        provinceList.scrollTop = offset - provinceList.clientHeight / 2 + sel.offsetHeight / 2;
      }
    }, 50);
  }

  function closeProvincePicker() {
    if (!provinceOverlay) return;
    // Blur search input first to prevent browser from scrolling page to show focused element
    if (provinceSearch) provinceSearch.blur();
    provinceOverlay.classList.remove('active');
    // Restore scroll position after picker closes
    _restoreActiveScrollTop(_savedScrollTop);
    _savedScrollTop = 0;
  }

  function initProvincePicker() {
    provinceOverlay = document.getElementById('province-overlay');
    provinceTrigger = document.getElementById('province-trigger');
    provinceDisplay = document.getElementById('province-display');
    provinceClose = document.getElementById('province-close');
    provinceList = document.getElementById('province-list');
    provinceSearch = document.getElementById('province-search');

    if (provinceTrigger) {
      provinceTrigger.addEventListener('click', e => { e.preventDefault(); openProvincePicker(); });
    }
    if (provinceClose) {
      provinceClose.addEventListener('click', e => { e.preventDefault(); closeProvincePicker(); });
    }
    if (provinceOverlay) {
      provinceOverlay.addEventListener('click', e => { if (e.target === provinceOverlay) closeProvincePicker(); });
      // Prevent touchmove on overlay backdrop from scrolling the page behind it (iOS Safari compat)
      provinceOverlay.addEventListener('touchmove', function(e) {
        if (provinceList && provinceList.contains(e.target)) return;
        e.preventDefault();
      }, { passive: false });
    }
    if (provinceSearch) {
      provinceSearch.addEventListener('input', e => renderProvinceList(e.target.value));
    }
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && provinceOverlay?.classList.contains('active')) closeProvincePicker();
    });
  }

  // ============================================
  // 地域选择器
  // ============================================
  function renderRegionList() {
    if (!regionList || !appData.preferences) return;
    var regions = appData.preferences.regions || [];
    regionList.innerHTML = regions.map(function (r) {
      var isSelected = r === selectedRegion;
      return '<div class="picker-item' + (isSelected ? ' selected' : '') + '" data-region="' + r + '">' +
        '<span>' + r + '</span>' +
        (isSelected
          ? '<svg class="check-icon" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 9 7 12 14 5"/></svg>'
          : '') +
        '</div>';
    }).join('');

    regionList.querySelectorAll('.picker-item').forEach(function (item) {
      item.addEventListener('click', function () {
        selectedRegion = item.getAttribute('data-region');
        if (regionDisplay) regionDisplay.textContent = selectedRegion;
        closeRegionPicker();
      });
    });
  }

  function openRegionPicker() {
    if (!regionOverlay) return;
    renderRegionList();
    _savedScrollTop = _getActiveScrollTop();
    regionOverlay.classList.add('active');
  }

  function closeRegionPicker() {
    if (!regionOverlay) return;
    regionOverlay.classList.remove('active');
    _restoreActiveScrollTop(_savedScrollTop);
    _savedScrollTop = 0;
  }

  function initRegionPicker() {
    regionOverlay = document.getElementById('region-overlay');
    regionTrigger = document.getElementById('region-select');
    regionDisplay = document.getElementById('region-display');
    regionClose = document.getElementById('region-close');
    regionList = document.getElementById('region-list');

    if (regionTrigger) {
      regionTrigger.addEventListener('click', function (e) { e.preventDefault(); openRegionPicker(); });
    }
    if (regionClose) {
      regionClose.addEventListener('click', function (e) { e.preventDefault(); closeRegionPicker(); });
    }
    if (regionOverlay) {
      regionOverlay.addEventListener('click', function (e) { if (e.target === regionOverlay) closeRegionPicker(); });
      regionOverlay.addEventListener('touchmove', function(e) {
        if (regionList && regionList.contains(e.target)) return;
        e.preventDefault();
      }, { passive: false });
    }
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && regionOverlay && regionOverlay.classList.contains('active')) closeRegionPicker();
    });
  }

  // ============================================
  // 事件绑定
  // ============================================
  function bindNavLinks(scope) {
    const root = scope || document;
    root.querySelectorAll('[data-nav]').forEach(el => {
      el.addEventListener('click', e => {
        e.preventDefault();
        navigateTo(el.getAttribute('data-nav'));
      });
    });
  }

  function bindBackButtons() {
    document.querySelectorAll('.back-btn').forEach(btn => {
      btn.addEventListener('click', e => { e.preventDefault(); goBack(); });
    });
  }

  function bindTabItems() {
    document.querySelectorAll('.tab-item').forEach(item => {
      item.addEventListener('click', () => {
        const tab = item.getAttribute('data-tab');
        if (tab === 'home') {
          navigateTo('page-home', false);
        } else if (tab === 'plan') {
          navigateTo('page-results');
        } else {
          const tabBar = item.closest('.tab-pill');
          tabBar.querySelectorAll('.tab-item').forEach(i => i.classList.remove('active'));
          item.classList.add('active');
        }
      });
    });
  }

  function bindScoreInput() {
    const scoreInput = document.getElementById('score-input');
    if (!scoreInput) return;
    scoreInput.addEventListener('input', e => {
      let val = e.target.value.replace(/\D/g, '');
      if (val.length > 3) val = val.slice(0, 3);
      e.target.value = val;
      scoreInput.classList.remove('error');
      var hint = document.getElementById('score-hint');
      if (hint) hint.style.display = 'none';
    });
  }

  // ============================================
  // 认证事件绑定
  // ============================================
  function bindAuthEvents() {
    // Tab 切换：登录 / 注册
    document.querySelectorAll('.auth-tab').forEach(function (tab) {
      tab.addEventListener('click', function () {
        var target = tab.getAttribute('data-auth-tab');
        document.querySelectorAll('.auth-tab').forEach(function (t) { t.classList.remove('active'); });
        tab.classList.add('active');
        document.getElementById('auth-login-form').style.display = target === 'login' ? '' : 'none';
        document.getElementById('auth-register-form').style.display = target === 'register' ? '' : 'none';
        // 清除错误提示
        document.getElementById('login-error').textContent = '';
        document.getElementById('register-error').textContent = '';
      });
    });

    // 登录提交
    var loginBtn = document.getElementById('login-submit');
    if (loginBtn) {
      loginBtn.addEventListener('click', function () {
        var phone = document.getElementById('login-phone').value.trim();
        var password = document.getElementById('login-password').value.trim();
        var errorEl = document.getElementById('login-error');

        if (!phone || phone.length !== 11) {
          errorEl.textContent = '请输入11位手机号';
          return;
        }
        if (!password) {
          errorEl.textContent = '请输入密码';
          return;
        }

        errorEl.textContent = '';
        loginBtn.textContent = '登录中...';
        loginBtn.disabled = true;

        api.auth.login(phone, password)
          .then(function (data) {
            Auth.setToken(data.token);
            Auth.user = data.user;
            Auth.profile = data.profile;
            if (Auth.profile) prefillForm(Auth.profile);
            updateGreeting();
            navigateTo('page-home', false);
          })
          .catch(function (err) {
            errorEl.textContent = err.message || '登录失败';
          })
          .finally(function () {
            loginBtn.textContent = '登录';
            loginBtn.disabled = false;
          });
      });
    }

    // 注册提交
    var registerBtn = document.getElementById('register-submit');
    if (registerBtn) {
      registerBtn.addEventListener('click', function () {
        var phone = document.getElementById('register-phone').value.trim();
        var nickname = document.getElementById('register-nickname').value.trim();
        var password = document.getElementById('register-password').value.trim();
        var errorEl = document.getElementById('register-error');

        if (!phone || phone.length !== 11) {
          errorEl.textContent = '请输入11位手机号';
          return;
        }
        if (!password || password.length < 6) {
          errorEl.textContent = '密码至少6位';
          return;
        }

        errorEl.textContent = '';
        registerBtn.textContent = '注册中...';
        registerBtn.disabled = true;

        api.auth.register(phone, password, nickname)
          .then(function (data) {
            Auth.setToken(data.token);
            Auth.user = data.user;
            Auth.profile = null;
            updateGreeting();
            navigateTo('page-home', false);
          })
          .catch(function (err) {
            errorEl.textContent = err.message || '注册失败';
          })
          .finally(function () {
            registerBtn.textContent = '注册';
            registerBtn.disabled = false;
          });
      });
    }

    // 退出登录
    var logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
      logoutBtn.addEventListener('click', function () {
        Auth.clear();
        // 清空表单
        var scoreInput = document.getElementById('score-input');
        if (scoreInput) scoreInput.value = '';
        document.querySelectorAll('.subject-btn.selected').forEach(function (btn) { btn.classList.remove('selected'); });
        document.querySelectorAll('.chip.selected').forEach(function (chip) { chip.classList.remove('selected'); });
        document.querySelectorAll('.strategy-card.selected').forEach(function (card) { card.classList.remove('selected'); });
        // 清空登录表单
        document.getElementById('login-phone').value = '';
        document.getElementById('login-password').value = '';
        document.getElementById('register-phone').value = '';
        document.getElementById('register-nickname').value = '';
        document.getElementById('register-password').value = '';
        navigateTo('page-auth', false);
      });
    }

    // 回车键支持
    var loginPwd = document.getElementById('login-password');
    if (loginPwd) {
      loginPwd.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') document.getElementById('login-submit').click();
      });
    }
    var regPwd = document.getElementById('register-password');
    if (regPwd) {
      regPwd.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') document.getElementById('register-submit').click();
      });
    }
  }

  // ============================================
  // 档案预填 & 问候语更新
  // ============================================
  function prefillForm(profile) {
    if (!profile) return;

    // 分数
    var scoreInput = document.getElementById('score-input');
    if (scoreInput && profile.score) scoreInput.value = profile.score;

    // 省份
    if (profile.province) {
      selectedProvince = profile.province;
      if (provinceDisplay) provinceDisplay.textContent = profile.province;
    }

    // 选考科目
    if (profile.subjects && profile.subjects.length > 0) {
      document.querySelectorAll('.subject-btn').forEach(function (btn) {
        var name = btn.textContent.trim();
        btn.classList.toggle('selected', profile.subjects.indexOf(name) !== -1);
      });
    }

    // 院校层次
    if (profile.schoolLevels && profile.schoolLevels.length > 0) {
      document.querySelectorAll('#school-level-chips .chip').forEach(function (chip) {
        var name = chip.textContent.trim();
        chip.classList.toggle('selected', profile.schoolLevels.indexOf(name) !== -1);
      });
    }

    // 专业方向
    if (profile.majors && profile.majors.length > 0) {
      document.querySelectorAll('#major-chips .chip').forEach(function (chip) {
        var name = chip.textContent.trim();
        chip.classList.toggle('selected', profile.majors.indexOf(name) !== -1);
      });
    }

    // 优先策略
    if (profile.strategy) {
      document.querySelectorAll('.strategy-card').forEach(function (card) {
        var text = card.querySelector('.text');
        if (text && text.textContent.trim() === profile.strategy) {
          card.classList.add('selected');
        } else {
          card.classList.remove('selected');
        }
      });
    }

    // 目标地域
    if (profile.region) {
      selectedRegion = profile.region;
      var regionEl = document.getElementById('region-display');
      if (regionEl) regionEl.textContent = profile.region;
    }
  }

  function updateGreeting() {
    var greetingEl = document.getElementById('greeting-text');
    if (greetingEl && Auth.user) {
      var name = Auth.user.nickname || '同学';
      greetingEl.textContent = '\u4f60\u597d\uff0c' + name + ' \ud83d\udc4b';
    }
  }

  // ============================================
  // 用户数据采集
  // ============================================
  function collectUserData() {
    var scoreInput = document.getElementById('score-input');
    var score = scoreInput ? parseInt(scoreInput.value.trim(), 10) : 0;

    if (!score) {
      scoreInput.classList.add('error');
      var hint = document.getElementById('score-hint');
      if (hint) hint.style.display = 'block';
      navigateTo('page-score');
      return null;
    }

    var province = selectedProvince || '';

    var subjects = [];
    document.querySelectorAll('.subject-btn.selected').forEach(function (btn) {
      subjects.push(btn.textContent.trim());
    });

    var schoolLevels = [];
    document.querySelectorAll('#school-level-chips .chip.selected').forEach(function (chip) {
      schoolLevels.push(chip.textContent.trim());
    });

    var majors = [];
    document.querySelectorAll('#major-chips .chip.selected').forEach(function (chip) {
      majors.push(chip.textContent.trim());
    });

    var strategy = '';
    var selStrategy = document.querySelector('.strategy-card.selected .text');
    if (selStrategy) strategy = selStrategy.textContent.trim();

    var region = selectedRegion || '';

    return {
      score: score,
      province: province,
      subjects: subjects,
      schoolLevels: schoolLevels,
      majors: majors,
      strategy: strategy,
      region: region
    };
  }

  // ============================================
  // 生成中动画 — 步骤循环推进
  // ============================================
  var _genSteps = [
    { label: '分析成绩与位次', status: 'doing' },
    { label: '匹配院校与专业', status: 'pending' },
    { label: '计算录取概率', status: 'pending' },
    { label: '生成推荐方案', status: 'pending' }
  ];

  function renderGenSteps() {
    var container = document.getElementById('generating-steps');
    if (!container) return;
    var indicators = { done: '\u2713', doing: '\u21bb', pending: '' };
    container.innerHTML = _genSteps.map(function (s) {
      return '<div class="step-item ' + s.status + '">' +
        '<div class="step-indicator">' + (indicators[s.status] || '') + '</div>' +
        '<span class="step-label">' + s.label + '</span>' +
        '</div>';
    }).join('');
  }

  function startStepAnimation() {
    _genSteps.forEach(function (s, i) { s.status = i === 0 ? 'doing' : 'pending'; });
    renderGenSteps();

    var idx = 0;
    return setInterval(function () {
      if (idx < _genSteps.length - 1) {
        _genSteps[idx].status = 'done';
        idx++;
        _genSteps[idx].status = 'doing';
        renderGenSteps();
      }
    }, 1500);
  }

  function finishSteps() {
    _genSteps.forEach(function (s) { s.status = 'done'; });
    renderGenSteps();
  }

  function showGenerationError(message) {
    var container = document.querySelector('.generating-container');
    if (!container) return;
    container.innerHTML =
      '<div style="text-align:center;display:flex;flex-direction:column;align-items:center;gap:16px;">' +
      '<div style="font-size:48px;">\u26a0\ufe0f</div>' +
      '<div style="font-size:18px;font-weight:600;">\u751f\u6210\u5931\u8d25</div>' +
      '<div style="font-size:14px;color:var(--color-text-secondary);max-width:280px;line-height:1.6;">' +
      (message || '\u670d\u52a1\u5668\u5f02\u5e38\uff0c\u8bf7\u91cd\u8bd5') + '</div>' +
      '<button class="cta-btn" id="retry-btn" style="width:auto;padding:0 32px;">\u8fd4\u56de\u91cd\u8bd5</button>' +
      '</div>';
    var retryBtn = document.getElementById('retry-btn');
    if (retryBtn) retryBtn.addEventListener('click', function () { goBack(); });
  }

  // ============================================
  // 事件绑定：核心流程按钮
  // ============================================
  function bindFlowButtons() {
    var nextBtn = document.getElementById('next-to-preference');
    if (nextBtn) {
      nextBtn.addEventListener('click', function () {
        var scoreInput = document.getElementById('score-input');
        var val = scoreInput ? scoreInput.value.trim() : '';
        if (!val) {
          scoreInput.classList.add('error');
          var hint = document.getElementById('score-hint');
          if (hint) hint.style.display = 'block';
          return;
        }
        navigateTo('page-preference');
      });
    }

    var genBtn = document.getElementById('cta-to-generating');
    if (genBtn) {
      genBtn.addEventListener('click', function () {
        // 1. 采集用户数据
        var userData = collectUserData();
        if (!userData) return;

        // 2. 保存档案到数据库（异步，不阻塞生成流程）
        if (Auth.isLoggedIn()) {
          api.auth.updateProfile(userData).catch(function (err) {
            console.warn('[App] 档案保存失败:', err);
          });
        }

        // 3. 跳转到生成中页面
        navigateTo('page-generating');

        // 4. 启动步骤动画
        var stepTimer = startStepAnimation();

        // 5. 调用 LLM 生成方案
        api.generatePlan(userData)
          .then(function (data) {
            clearInterval(stepTimer);
            finishSteps();
            appData.recommendations = data;
            renderRecommendations();
            setTimeout(function () { navigateTo('page-results'); }, 600);
          })
          .catch(function (err) {
            clearInterval(stepTimer);
            console.error('[App] Generation failed:', err);
            showGenerationError(err.message || '\u670d\u52a1\u5668\u5f02\u5e38');
          });
      });
    }
  }

  // ============================================
  // 涟漪效果 — CTA 按钮点击时从点击位置扩散水波纹
  // ============================================
  function bindRippleEffect() {
    document.querySelectorAll('.cta-btn').forEach(function (btn) {
      if (btn._rippleBound) return;
      btn._rippleBound = true;
      btn.addEventListener('click', function (e) {
        var rect = btn.getBoundingClientRect();
        var size = Math.max(rect.width, rect.height);
        var x = e.clientX - rect.left - size / 2;
        var y = e.clientY - rect.top - size / 2;

        var ripple = document.createElement('span');
        ripple.className = 'ripple';
        ripple.style.width = ripple.style.height = size + 'px';
        ripple.style.left = x + 'px';
        ripple.style.top = y + 'px';

        btn.appendChild(ripple);
        ripple.addEventListener('animationend', function () {
          if (ripple.parentNode) ripple.parentNode.removeChild(ripple);
        });
      });
    });
  }

  // ============================================
  // 初始化
  // ============================================
  function init() {
    // --- 1. 加载静态配置 ---
    var configFiles = [
      'data/provinces.json',
      'data/score-input.json',
      'data/preferences.json'
    ];

    Promise.all(configFiles.map(function (url) { return fetch(url).then(function (r) { return r.json(); }); }))
      .then(function (configResults) {
        appData.provinces   = configResults[0];
        appData.scoreInput  = configResults[1];
        appData.preferences = configResults[2];

        return api.getGeneratingSteps();
      })
      .then(function (apiResult) {
        appData.generatingSteps = apiResult;

        // --- 2. 渲染 ---
        renderSubjects();
        renderPreferences();
        renderGeneratingSteps();

        // 省份默认值
        selectedProvince = (appData.scoreInput && appData.scoreInput.defaultProvince) || '浙江省';
        if (provinceDisplay) provinceDisplay.textContent = selectedProvince;

        // 初始化省份选择器
        initProvincePicker();

        // 初始化地域选择器
        initRegionPicker();

        // 绑定事件
        bindNavLinks(document);
        bindBackButtons();
        bindTabItems();
        bindScoreInput();
        bindFlowButtons();
        bindAuthEvents();
        bindRippleEffect();

        // --- 3. 认证检查 ---
        if (Auth.isLoggedIn()) {
          // 有 token：验证 → 加载档案 → 预填 → 进入首页
          api.auth.getMe()
            .then(function (data) {
              Auth.user = data.user;
              return api.auth.getProfile();
            })
            .then(function (data) {
              Auth.profile = data.profile;
              if (Auth.profile) prefillForm(Auth.profile);
              updateGreeting();
              navigateTo('page-home', false);
              console.log('[App] 已登录用户，档案已加载');
            })
            .catch(function (err) {
              // token 无效或过期
              console.warn('[App] Token 无效，跳转登录页:', err.message);
              Auth.clear();
              navigateTo('page-auth', false);
            });
        } else {
          // 无 token：显示登录页
          navigateTo('page-auth', false);
          console.log('[App] 未登录，显示登录页');
        }

        console.log('高考志愿填报 App 初始化完成 ✓ — USE_MOCK=' + USE_MOCK);
      })
      .catch(function (err) {
        console.error('数据加载失败:', err);
        // 降级：仍然初始化导航和登录页
        bindNavLinks(document);
        bindBackButtons();
        bindTabItems();
        bindScoreInput();
        bindFlowButtons();
        bindAuthEvents();
        bindRippleEffect();
        navigateTo('page-auth', false);
      });
  }

  // provinceDisplay 在 initProvincePicker 中赋值，但 bindScoreInput 可能先调用
  provinceDisplay = document.getElementById('province-display');

  init();
})();
