// AI Pulse - App Logic
var currentFilter = 'all';
var currentSearch = '';
var PER_PAGE = 9;
var currentPage = 1;

function getFiltered() {
  return articles.filter(function(a) {
    var matchFilter = currentFilter === 'all' || a.tags.indexOf(currentFilter) !== -1;
    var matchSearch = !currentSearch
      || a.title.toLowerCase().indexOf(currentSearch) !== -1
      || a.summary.toLowerCase().indexOf(currentSearch) !== -1
      || (a.insight || '').toLowerCase().indexOf(currentSearch) !== -1
      || a.tags.some(function(t) { return t.toLowerCase().indexOf(currentSearch) !== -1; });
    return matchFilter && matchSearch;
  });
}

function renderHero() {
  var latest = articles[0];
  if (!latest) return;
  var el = document.getElementById('heroSection');
  el.innerHTML = '<div class="hero-card" onclick="openModal(0)">'
    + '<div class="hero-badge">LATEST</div>'
    + '<div class="hero-date">' + latest.date + '</div>'
    + '<div class="hero-title">' + latest.title + '</div>'
    + '<div class="hero-excerpt">' + latest.summary.substring(0, 200) + '...</div>'
    + '<div class="hero-tags">' + latest.tags.map(function(t) { return '<span class="hero-tag">' + t + '</span>'; }).join('') + '</div>'
    + '</div>';
}

function renderGrid() {
  var filtered = getFiltered();
  var start = (currentPage - 1) * PER_PAGE;
  var paged = filtered.slice(start, start + PER_PAGE);
  var grid = document.getElementById('articlesGrid');
  var filterLabel = currentFilter === 'all' ? '最新情報' : currentFilter;

  document.getElementById('sectionTitle').textContent = currentSearch ? '搜尋：' + currentSearch : filterLabel;
  document.getElementById('sectionCount').textContent = '共 ' + filtered.length + ' 則';

  if (paged.length === 0) {
    grid.innerHTML = '<div class="no-results">沒有找到符合條件的新聞 &#128269;</div>';
    document.getElementById('pagination').innerHTML = '';
    return;
  }

  grid.innerHTML = paged.map(function(a) {
    var globalIdx = articles.indexOf(a);
    var priorityClass = a.priority || 'normal';
    var priorityLabel = priorityClass === 'high' ? '重要' : (priorityClass === 'medium' ? '關注' : '一般');
    return '<div class="article-card" onclick="openModal(' + globalIdx + ')">'
      + '<div class="card-color-bar" style="background:' + a.color + '"></div>'
      + '<div class="card-body">'
      + '<div class="card-meta">'
      + '<span class="card-date">' + a.date + '</span>'
      + '<span class="card-priority ' + priorityClass + '">' + priorityLabel + '</span>'
      + '<div class="card-tags">' + a.tags.map(function(t) { return '<span class="card-tag tag-' + t + '">' + t + '</span>'; }).join('') + '</div>'
      + '</div>'
      + '<div class="card-title">' + a.title + '</div>'
      + '<div class="card-excerpt">' + a.summary.substring(0, 150) + '...</div>'
      + '</div>'
      + '<div class="card-footer">'
      + '<span class="card-read-more">閱讀更多 &rarr;</span>'
      + '<span class="card-source">' + ((a.sources && a.sources[0]) ? a.sources[0].name : '') + '</span>'
      + '</div>'
      + '</div>';
  }).join('');

  renderPagination(filtered.length);
}

function renderPagination(total) {
  var totalPages = Math.ceil(total / PER_PAGE);
  var pag = document.getElementById('pagination');
  if (totalPages <= 1) { pag.innerHTML = ''; return; }
  var html = '<button class="page-btn" onclick="goPage(' + (currentPage - 1) + ')"' + (currentPage === 1 ? ' disabled' : '') + '>&lsaquo; 上一頁</button>';
  for (var p = 1; p <= totalPages; p++) {
    html += '<button class="page-btn' + (p === currentPage ? ' active' : '') + '" onclick="goPage(' + p + ')">' + p + '</button>';
  }
  html += '<button class="page-btn" onclick="goPage(' + (currentPage + 1) + ')"' + (currentPage === totalPages ? ' disabled' : '') + '>下一頁 &rsaquo;</button>';
  pag.innerHTML = html;
}

function goPage(p) {
  currentPage = p;
  renderGrid();
  var header = document.querySelector('.section-header');
  if (header) window.scrollTo({ top: header.offsetTop - 80, behavior: 'smooth' });
}

function openModal(idx) {
  var a = articles[idx];
  document.getElementById('modalMeta').innerHTML =
    '<span class="card-date">' + a.date + '</span>'
    + a.tags.map(function(t) { return '<span class="card-tag tag-' + t + '">' + t + '</span>'; }).join('');
  document.getElementById('modalTitle').textContent = a.title;
  document.getElementById('modalBody').innerHTML =
    '<div class="summary">' + a.summary + '</div>'
    + (a.insight ? '<div class="insight"><strong>&#127919; 深度分析：</strong><br>' + a.insight + '</div>' : '')
    + (a.takeaway ? '<div class="takeaway"><strong>&#9989; 重點摘要：</strong><br>' + a.takeaway + '</div>' : '')
    + '<div class="source">來源：' + (a.sources || []).map(function(s) { return '<a href="' + s.url + '" target="_blank" rel="noopener">' + s.name + '</a>'; }).join(' | ') + '</div>';
  document.getElementById('modal').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  document.getElementById('modal').classList.remove('open');
  document.body.style.overflow = '';
}

function resetAll() {
  currentFilter = 'all';
  currentSearch = '';
  currentPage = 1;
  document.getElementById('searchInput').value = '';
  document.querySelectorAll('.nav-link').forEach(function(l) { l.classList.remove('active'); });
  document.querySelector('.nav-link[data-filter="all"]').classList.add('active');
  renderHero();
  renderGrid();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// Event Listeners
document.querySelectorAll('.nav-link').forEach(function(link) {
  link.addEventListener('click', function() {
    document.querySelectorAll('.nav-link').forEach(function(l) { l.classList.remove('active'); });
    link.classList.add('active');
    currentFilter = link.dataset.filter;
    currentPage = 1;
    renderGrid();
  });
});

document.getElementById('searchInput').addEventListener('input', function(e) {
  currentSearch = e.target.value.toLowerCase().trim();
  currentPage = 1;
  renderGrid();
});

document.getElementById('modalClose').addEventListener('click', closeModal);
document.getElementById('modal').addEventListener('click', function(e) {
  if (e.target === e.currentTarget) closeModal();
});
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') closeModal();
});
document.getElementById('navToggle').addEventListener('click', function() {
  document.getElementById('navLinks').classList.toggle('open');
});

// Initial render
renderHero();
renderGrid();
