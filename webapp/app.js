// Initialize Chart.js styling defaults globally
Chart.defaults.color = '#94a3b8';
Chart.defaults.font.family = "'Inter', sans-serif";
Chart.defaults.scale.grid.color = 'rgba(255, 255, 255, 0.05)';
Chart.defaults.plugins.tooltip.padding = 12;

let pulseChartInstance = null;
let categoryChartInstance = null;

// ---------- Mock Data Injection ---------- //
const mockData = {
    user: { name: 'Ido' },
    budget: { total: 5000, spent: 3450, savings: 0 },
    netFlow: { income: 8200, expenses: 3450 },
    cashFlowSeries: {
        labels: ['1st', '5th', '10th', '15th', '20th', '25th', '30th'],
        income: [0, 8200, 8200, 8200, 8200, 8200, 8200],
        expenses: [120, 850, 1400, 1950, 2400, 3100, 3450]
    },
    categories: {
        'Housing': 1500,
        'Food': 850,
        'Transport': 400,
        'Shopping': 450,
        'Entertainment': 250
    },
    goal: { name: 'Vacation', target: 10000, current: 6500 },
    transactions: [
        { id: 1, title: 'Salary', category: 'Income', amount: 8200, type: 'inc', time: '2 days ago', icon: '💼' },
        { id: 2, title: 'Uber', category: 'Transport', amount: 45, type: 'exp', time: '5 hours ago', icon: '🚗' },
        { id: 3, title: 'Supermarket', category: 'Food', amount: 320, type: 'exp', time: '1 day ago', icon: '🍔' },
        { id: 4, title: 'Netflix', category: 'Entertainment', amount: 40, type: 'exp', time: '2 days ago', icon: '🎉' },
        { id: 5, title: 'Rent', category: 'Housing', amount: 1500, type: 'exp', time: '3 days ago', icon: '🏠' }
    ],
    insight: `
        <p><strong>🔍 Observation:</strong> Your income arrived on the 5th, safely padding your account early. However, Food and Shopping are consuming 37% of your budget mid-month.</p>
        <p><strong>💡 Strategy:</strong> Implementing the 'pay-yourself-first' rule—moving 20% of income directly to investments before expenses hit—creates artificial scarcity, capping discretionary spread.</p>
        <p><strong>🎯 Action:</strong> Consider setting a strict ₪200 weekly limit for dining out starting next Sunday.</p>
    `
};

let currentPeriodData = JSON.parse(JSON.stringify(mockData)); // Deep copy to modify

// ---------- UI Updaters ---------- //
function updateBudgetUI() {
    const budgetPct = currentPeriodData.budget.total > 0 ? (currentPeriodData.budget.spent / currentPeriodData.budget.total) * 100 : 0;
    document.getElementById('budget-spent').textContent = `₪${currentPeriodData.budget.spent.toLocaleString()}`;
    document.getElementById('budget-total').textContent = `₪${currentPeriodData.budget.total.toLocaleString()}`;
    document.getElementById('budget-remaining').textContent = `₪${Math.max(0, currentPeriodData.budget.total - currentPeriodData.budget.spent).toLocaleString()} remaining`;
    document.getElementById('savings-amount').textContent = `₪${currentPeriodData.budget.savings.toLocaleString()}`;

    const pctTag = document.getElementById('budget-percent');
    pctTag.textContent = `${Math.round(budgetPct)}%`;
    if (budgetPct > 80) pctTag.classList.add('danger');
    else pctTag.classList.remove('danger');

    const fill = document.getElementById('budget-fill');
    fill.style.width = `${Math.min(100, budgetPct)}%`;
    if (budgetPct > 85) fill.classList.add('warning');
    else fill.classList.remove('warning');
}

function updateHeaderUI() {
    const net = currentPeriodData.netFlow.income - currentPeriodData.netFlow.expenses;
    const netEl = document.getElementById('net-cash-flow');
    netEl.textContent = `₪${net.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    netEl.classList.remove('positive', 'negative');
    netEl.classList.add(net >= 0 ? 'positive' : 'negative');
}

function updateGoalUI() {
    const pct = Math.min(100, (currentPeriodData.goal.current / currentPeriodData.goal.target) * 100);
    document.getElementById('goal-pct').textContent = `${Math.round(pct)}%`;
    document.getElementById('goal-saved').textContent = `₪${currentPeriodData.goal.current.toLocaleString()}`;
    document.getElementById('goal-name-display').textContent = currentPeriodData.goal.name;
    document.getElementById('goal-target-display').textContent = `₪${currentPeriodData.goal.target.toLocaleString()}`;

    // Animate circular progress
    setTimeout(() => {
        const circle = document.getElementById('goal-progress');
        // We use conic-gradient to draw the ring. The CSS variable handles the color.
        const isLight = document.body.classList.contains('theme-light');
        const bg = isLight ? 'rgba(0,0,0,0.05)' : 'rgba(255,255,255,0.05)';
        circle.style.background = `conic-gradient(var(--accent-inc) ${pct * 3.6}deg, ${bg} 0deg)`;
    }, 300);
}

function updateTransactionsUI() {
    const listEl = document.getElementById('transaction-list');
    listEl.innerHTML = '';

    if (!currentPeriodData.transactions || currentPeriodData.transactions.length === 0) {
        listEl.innerHTML = '<div class="tx-empty">No transactions found for this period.</div>';
        return;
    }

    currentPeriodData.transactions.forEach(tx => {
        const sign = tx.type === 'inc' ? '+' : '-';
        const html = `
            <div class="tx-item">
                <div class="tx-left">
                    <div class="tx-icon">${tx.icon}</div>
                    <div class="tx-details">
                        <span class="tx-title">${tx.title}</span>
                        <span class="tx-category">${tx.category}</span>
                    </div>
                </div>
                <div class="tx-right">
                    <span class="tx-amount ${tx.type}">${sign}₪${tx.amount.toLocaleString()}</span>
                    <span class="tx-time">${tx.time}</span>
                </div>
            </div>
        `;
        listEl.insertAdjacentHTML('beforeend', html);
    });
}

document.addEventListener('DOMContentLoaded', async () => {
    // Phase 2: Bot Integration 
    const tg = window.Telegram.WebApp;
    tg.expand();

    await loadPreferences();
    initDashboard();
});

async function initDashboard(year = null, month = null) {
    const tg = window.Telegram.WebApp;
    const initData = tg.initData || "";

    try {
        let url = `/api/webapp/dashboard`;
        let params = [];
        if (year) params.push(`year=${year}`);
        if (month !== null) params.push(`month=${month}`);
        if (params.length) url += `?${params.join('&')}`;

        const dashRes = await fetch(url, {
            headers: { 'Authorization': `WebAppData ${initData}` }
        });
        if (!dashRes.ok) throw new Error('API Error');
        const dashData = await dashRes.json();

        let catUrl = `/api/webapp/categories`;
        if (params.length) catUrl += `?${params.join('&')}`;
        const catRes = await fetch(catUrl, {
            headers: { 'Authorization': `WebAppData ${initData}` }
        });
        const catData = await catRes.ok ? await catRes.json() : {};

        mockData.budget = dashData.budget;
        mockData.netFlow = dashData.netFlow;
        mockData.cashFlowSeries = dashData.cashFlowSeries;
        mockData.transactions = dashData.transactions;
        mockData.goal = dashData.goal;
        mockData.insight = dashData.insight;
        mockData.categories = catData;

        currentPeriodData = JSON.parse(JSON.stringify(mockData));

        updateHeaderUI();
        updateBudgetUI();
        updateGoalUI();
        updateTransactionsUI();
        renderPulseChart();
        renderCategoryChart();

        const insightEl = document.getElementById('ai-insight');
        insightEl.innerHTML = dashData.insight || "<p>No insights for this period.</p>";
        insightEl.classList.remove('skeleton-line', 'short');

    } catch (e) {
        console.error("Dashboard Load Error:", e);
        currentPeriodData = JSON.parse(JSON.stringify(mockData));
        updateHeaderUI();
        updateBudgetUI();
        updateGoalUI();
        updateTransactionsUI();
        renderPulseChart();
        renderCategoryChart();

        const insightEl = document.getElementById('ai-insight');
        insightEl.innerHTML = mockData.insight;
        insightEl.classList.remove('skeleton-line', 'short');
    }
}

// 4. Pulse Chart (Line)
const renderPulseChart = () => {
    if (pulseChartInstance) pulseChartInstance.destroy();
    const ctxPulse = document.getElementById('pulseChart').getContext('2d');

    // Dynamic colors based on theme
    const isMono = document.getElementById('color-select').value === 'monochrome';
    const incColor = isMono ? '#94a3b8' : '#10b981';
    const expColor = isMono ? '#475569' : '#f43f5e';

    const gradInc = ctxPulse.createLinearGradient(0, 0, 0, 400);
    gradInc.addColorStop(0, `rgba(${isMono ? '148,163,184' : '16,185,129'}, 0.4)`);
    gradInc.addColorStop(1, `rgba(${isMono ? '148,163,184' : '16,185,129'}, 0.0)`);

    const gradExp = ctxPulse.createLinearGradient(0, 0, 0, 400);
    gradExp.addColorStop(0, `rgba(${isMono ? '71,85,105' : '244,63,94'}, 0.4)`);
    gradExp.addColorStop(1, `rgba(${isMono ? '71,85,105' : '244,63,94'}, 0.0)`);

    pulseChartInstance = new Chart(ctxPulse, {
        type: 'line',
        data: {
            labels: currentPeriodData.cashFlowSeries.labels,
            datasets: [
                {
                    label: 'Income',
                    data: currentPeriodData.cashFlowSeries.income,
                    borderColor: '#10b981', // Emerald
                    backgroundColor: gradInc,
                    borderWidth: 3,
                    tension: 0.4, // Smooth curve
                    fill: true,
                    pointBackgroundColor: '#10b981',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 6
                },
                {
                    label: 'Expenses',
                    data: currentPeriodData.cashFlowSeries.expenses,
                    borderColor: '#f43f5e', // Rose
                    backgroundColor: gradExp,
                    borderWidth: 3,
                    tension: 0.4,
                    fill: true,
                    pointBackgroundColor: '#f43f5e',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 6
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(15, 23, 42, 0.95)',
                    titleFont: { family: "'Outfit', sans-serif", size: 14, weight: '600' },
                    bodyFont: { family: "'Inter', sans-serif", size: 13 },
                    padding: 14,
                    cornerRadius: 12,
                    borderColor: 'rgba(255,255,255,0.1)',
                    borderWidth: 1,
                    displayColors: true,
                    usePointStyle: true,
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    border: { display: false },
                    grid: { drawBorder: false, color: 'rgba(255,255,255,0.03)' },
                    ticks: {
                        callback: (val) => '₪' + val,
                        maxTicksLimit: 6,
                        padding: 10
                    }
                },
                x: {
                    border: { display: false },
                    grid: { display: false },
                    ticks: { padding: 10 }
                }
            }
        }
    });
};
renderPulseChart();

// 5. Category Donut Chart
const renderCategoryChart = () => {
    if (categoryChartInstance) categoryChartInstance.destroy();
    const ctxCat = document.getElementById('categoryChart').getContext('2d');
    const catLabels = Object.keys(currentPeriodData.categories);
    const catData = Object.values(currentPeriodData.categories);

    const isMono = document.getElementById('color-select').value === 'monochrome';
    const isOcean = document.getElementById('color-select').value === 'ocean';

    let bgColors = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899'];
    if (isMono) bgColors = ['#94a3b8', '#64748b', '#475569', '#334155', '#1e293b'];
    if (isOcean) bgColors = ['#0ea5e9', '#0284c7', '#0369a1', '#075985', '#0c4a6e'];

    categoryChartInstance = new Chart(ctxCat, {
        type: 'doughnut',
        data: {
            labels: catLabels,
            datasets: [{
                data: catData,
                backgroundColor: bgColors,
                borderWidth: 0,
                hoverOffset: 12
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '75%',
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        usePointStyle: true,
                        padding: 24,
                        font: { family: "'Inter', sans-serif", size: 12, weight: '500' }
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(15, 23, 42, 0.95)',
                    titleFont: { family: "'Outfit', sans-serif", size: 14 },
                    bodyFont: { family: "'Inter', sans-serif", size: 13, weight: '600' },
                    padding: 14,
                    cornerRadius: 12,
                    borderColor: 'rgba(255,255,255,0.1)',
                    borderWidth: 1,
                    callbacks: {
                        label: function (context) {
                            return ' ₪' + context.parsed.toLocaleString();
                        }
                    }
                }
            }
        }
    });
};
renderCategoryChart();

// ---------- Interactive Listeners ---------- //

// Period Controls
const viewTypeSelect = document.getElementById('view-type');
const monthGroup = document.getElementById('month-group');
const monthSelect = document.getElementById('month-select');
const yearSelect = document.getElementById('year-select');

// Default select current month
monthSelect.value = new Date().getMonth().toString();

function fetchAndRenderData() {
    const isYearly = viewTypeSelect.value === 'yearly';
    const year = parseInt(yearSelect.value);
    const month = isYearly ? null : parseInt(monthSelect.value);

    initDashboard(year, month);
}

viewTypeSelect.addEventListener('change', (e) => {
    if (e.target.value === 'yearly') {
        monthGroup.style.display = 'none';
    } else {
        monthGroup.style.display = 'flex';
    }
    fetchAndRenderData();
});

monthSelect.addEventListener('change', fetchAndRenderData);
yearSelect.addEventListener('change', fetchAndRenderData);

// User Budget Controls
document.getElementById('set-budget-btn').addEventListener('click', () => {
    const val = parseFloat(document.getElementById('new-budget').value);
    if (val > 0) {
        currentPeriodData.budget.total = val;
        updateBudgetUI();
        document.getElementById('new-budget').value = '';
        savePreferences();
    }
});

document.getElementById('add-savings-btn').addEventListener('click', () => {
    const val = parseFloat(document.getElementById('add-savings').value);
    if (val > 0) {
        currentPeriodData.budget.savings += val;
        updateBudgetUI();
        document.getElementById('add-savings').value = '';
    }
});

// Goal Edit Controls
const editGoalBtn = document.getElementById('edit-goal-btn');
const goalEditForm = document.getElementById('goal-edit-form');
const goalDisplaySection = document.getElementById('goal-display-section');
const saveGoalBtn = document.getElementById('save-goal-btn');

editGoalBtn.addEventListener('click', () => {
    goalDisplaySection.style.display = 'none';
    goalEditForm.style.display = 'block';
    document.getElementById('goal-name-input').value = currentPeriodData.goal.name;
    document.getElementById('goal-target-input').value = currentPeriodData.goal.target;
});

saveGoalBtn.addEventListener('click', () => {
    const newName = document.getElementById('goal-name-input').value || 'My Goal';
    const newTarget = parseFloat(document.getElementById('goal-target-input').value) || 1;

    currentPeriodData.goal.name = newName;
    currentPeriodData.goal.target = newTarget;
    mockData.goal.name = newName;   // Persist to underlying mock too
    mockData.goal.target = newTarget;

    goalEditForm.style.display = 'none';
    goalDisplaySection.style.display = 'block';
    updateGoalUI();
    savePreferences();
});

// Dashboard Layout Customizer (Drag & Drop + Visibility)
const layoutList = document.getElementById('widget-layout-list');
let draggables = document.querySelectorAll('.layout-item');

function applyLayout() {
    const items = layoutList.querySelectorAll('.layout-item');
    const layout = [];

    items.forEach((item, index) => {
        const widgetId = item.getAttribute('data-id');
        layout.push({ id: widgetId, hidden: item.classList.contains('hidden-item') });

        const widgetEl = document.querySelector(`[data-widget-id="${widgetId}"]`);
        if (widgetEl) {
            widgetEl.style.order = index;
            if (item.classList.contains('hidden-item')) {
                widgetEl.classList.add('hidden-widget');
            } else {
                widgetEl.classList.remove('hidden-widget');
            }
        }
    });

    savePreferences(layout);
}

async function savePreferences(layout = null) {
    const tg = window.Telegram.WebApp;
    const initData = tg.initData || "";

    // Determine layout if not provided
    let layoutToSave = layout;
    if (!layoutToSave) {
        const items = document.querySelectorAll('.layout-item');
        layoutToSave = Array.from(items).map(item => ({
            id: item.getAttribute('data-id'),
            hidden: item.classList.contains('hidden-item')
        }));
    }

    const prefs = {
        theme: document.body.classList.contains('theme-light') ? 'light' : 'dark',
        color: document.getElementById('color-select').value,
        lang: document.getElementById('lang-select').value,
        layout: JSON.stringify(layoutToSave),
        financial_goal: JSON.stringify(currentPeriodData.goal),
        budget_target: currentPeriodData.budget.total
    };

    // Offline / Local Storage fallback
    localStorage.setItem('fintech-prefs-offline', JSON.stringify(prefs));

    try {
        await fetch('/api/webapp/settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `WebAppData ${initData}`
            },
            body: JSON.stringify({
                theme: prefs.theme,
                layout: prefs.layout,
                budget_target: prefs.budget_target,
                financial_goal: prefs.financial_goal,
                language: prefs.lang,
                accent_color: prefs.color
            })
        });
    } catch (e) {
        console.warn("Could not save settings to server:", e);
    }
}

async function loadPreferences() {
    const tg = window.Telegram.WebApp;
    const initData = tg.initData || "";

    let prefs = null;
    try {
        const res = await fetch('/api/webapp/settings', {
            headers: { 'Authorization': `WebAppData ${initData}` }
        });
        if (res.ok) {
            const serverPrefs = await res.json();
            if (serverPrefs && serverPrefs.theme) {
                prefs = serverPrefs;
                // Normalize field names
                prefs.color = serverPrefs.accent_color;
                prefs.lang = serverPrefs.language;
            }
        }
    } catch (e) {
        console.warn("Could not load from server, using local fallback");
    }

    if (!prefs) {
        const saved = localStorage.getItem('fintech-prefs-offline');
        if (saved) prefs = JSON.parse(saved);
        else return;
    }

    try {
        // Apply Theme
        if (prefs.theme === 'light') {
            document.body.classList.add('theme-light');
            document.getElementById('theme-select').value = 'light';
        } else {
            document.body.classList.remove('theme-light');
            document.getElementById('theme-select').value = 'dark';
        }

        // Apply Aesthetic
        if (prefs.color || prefs.accent_color) {
            document.getElementById('color-select').value = prefs.color || prefs.accent_color;
        }

        // Apply Goal & Budget
        const goalData = prefs.financial_goal || prefs.userGoal;
        if (goalData) {
            const goal = typeof goalData === 'string' ? JSON.parse(goalData) : goalData;
            mockData.goal = goal;
            currentPeriodData.goal = goal;
        }
        const budget = prefs.budget_target || prefs.userBudget;
        if (budget) {
            mockData.budget.total = budget;
            currentPeriodData.budget.total = budget;
        }

        // Apply Language
        const lang = prefs.language || prefs.lang;
        if (lang === 'he') {
            document.body.dir = 'rtl';
            document.getElementById('lang-select').value = 'he';
        } else {
            document.body.dir = 'ltr';
            document.getElementById('lang-select').value = 'en';
        }

        // Apply Layout Order
        let layout = prefs.layout;
        if (typeof layout === 'string') layout = JSON.parse(layout);

        if (layout && Array.isArray(layout)) {
            const list = document.getElementById('widget-layout-list');
            layout.forEach(p => {
                const item = list.querySelector(`[data-id="${p.id}"]`);
                if (item) {
                    if (p.hidden) {
                        item.classList.add('hidden-item');
                        item.querySelector('.visibility-btn').textContent = '👁️‍🗨️';
                    }
                    list.appendChild(item);
                }
            });

            // Apply visual order (order CSS prop)
            const items = list.querySelectorAll('.layout-item');
            items.forEach((item, index) => {
                const widgetId = item.getAttribute('data-id');
                const widgetEl = document.querySelector(`[data-widget-id="${widgetId}"]`);
                if (widgetEl) {
                    widgetEl.style.order = index;
                    if (item.classList.contains('hidden-item')) widgetEl.classList.add('hidden-widget');
                    else widgetEl.classList.remove('hidden-widget');
                }
            });
        }
    } catch (e) {
        console.warn("Error applying preferences:", e);
    }
}

// Init Drag and Drop
let draggedItem = null;

layoutList.addEventListener('dragstart', (e) => {
    if (e.target.classList.contains('layout-item')) {
        draggedItem = e.target;
        setTimeout(() => e.target.classList.add('dragging'), 0);
    }
});

layoutList.addEventListener('dragend', (e) => {
    if (e.target.classList.contains('layout-item')) {
        e.target.classList.remove('dragging');
        draggedItem = null;
        applyLayout(); // Apply new order
    }
});

layoutList.addEventListener('dragover', (e) => {
    e.preventDefault();
    const afterElement = getDragAfterElement(layoutList, e.clientY);
    const draggable = document.querySelector('.dragging');
    if (draggable && afterElement !== draggable) {
        if (afterElement == null) {
            layoutList.appendChild(draggable);
        } else {
            layoutList.insertBefore(draggable, afterElement);
        }
    }
});

function getDragAfterElement(container, y) {
    const draggableElements = [...container.querySelectorAll('.layout-item:not(.dragging)')];
    return draggableElements.reduce((closest, child) => {
        const box = child.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;
        if (offset < 0 && offset > closest.offset) {
            return { offset: offset, element: child };
        } else {
            return closest;
        }
    }, { offset: Number.NEGATIVE_INFINITY }).element;
}

// Init Visibility Toggles
layoutList.addEventListener('click', (e) => {
    if (e.target.classList.contains('visibility-btn')) {
        const item = e.target.closest('.layout-item');
        item.classList.toggle('hidden-item');
        e.target.textContent = item.classList.contains('hidden-item') ? '👁️‍🗨️' : '👁️';
        applyLayout();
    }
});

// Apply default layout on load
applyLayout();

// Settings Modal
const modal = document.getElementById('settings-modal');
document.getElementById('open-settings').addEventListener('click', () => modal.classList.add('active'));
document.getElementById('close-settings').addEventListener('click', () => modal.classList.remove('active'));

// Theme Switcher
document.getElementById('theme-select').addEventListener('change', (e) => {
    if (e.target.value === 'light') document.body.classList.add('theme-light');
    else document.body.classList.remove('theme-light');

    Chart.defaults.scale.grid.color = e.target.value === 'light' ? 'rgba(0,0,0,0.05)' : 'rgba(255,255,255,0.05)';
    renderPulseChart();
    renderCategoryChart();
    savePreferences();
});

// Aesthetic Switcher
document.getElementById('color-select').addEventListener('change', () => {
    renderPulseChart();
    renderCategoryChart();
    savePreferences();
});

// Language Simulator
document.getElementById('lang-select').addEventListener('change', (e) => {
    const isRtl = e.target.value === 'he';
    document.body.dir = isRtl ? 'rtl' : 'ltr';
    document.querySelector('.greeting h1').innerHTML = isRtl ? 'שלום, עידו 👋' : 'Hello, Ido 👋';
    document.querySelector('.greeting p').innerHTML = isRtl ? 'ברוך הבא למרכז הבקרה האישי שלך.' : 'Welcome to your personal command center.';
    savePreferences();
});
