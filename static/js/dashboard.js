let LANG = "en";
let dashboardData = null;
let selectedMachine = null;

const TEXT = {
    zh: {
        title: "智慧製造即時監控 Dashboard",
        updated_at: "更新時間：",
        avg_health: "平均設備健康度",
        min_health: "最低設備健康度",
        capacity_factor: "產能修正係數",
        original_demand: "預測總需求",
        adjusted_demand: "預估總產出",
        risk_parts: "風險零件",
        summary: "系統摘要",
        po_table: "採購建議明細",
        risk_po: "風險零件數 / 建議採購量",
        loading: "資料更新中...",
        updated: "資料已更新",
        update_failed: "更新失敗：",
        no_risk_parts: "目前無風險零件",
        no_po_data: "目前無採購建議資料",
        part_no: "圖號",
        suggested_po_qty: "建議採購量",
        first_shortage_date: "最早缺料日",
        first_order_date: "建議下單日",
        first_eta: "需求到貨日",
        days_below_safety: "低於安全庫存天數",
        days_below_zero: "負庫存天數",
        max_shortage_qty: "最大缺口",
        min_available: "最低可用量",
        original_demand_legend: "預測需求",
        adjusted_demand_legend: "預估產出",
        gap_legend: "產能缺口",
        temperature: "溫度",
        vibration: "震動",
        health_score: "健康度",
        suggested_po_legend: "建議採購量",
        compare_chart_title: "未來 7 天需求 / 產出 / 缺口",
        iot_chart_title: "設備健康監控",
        po_chart_title: "Top 10 採購建議零件"
    },
    en: {
        title: "Smart Manufacturing Dashboard",
        updated_at: "Updated at:",
        avg_health: "Average Machine Health",
        min_health: "Minimum Machine Health",
        capacity_factor: "Capacity Adjustment",
        original_demand: "Forecast Demand",
        adjusted_demand: "Expected Output",
        risk_parts: "Risk Parts",
        summary: "System Summary",
        po_table: "Purchase Recommendations",
        risk_po: "Risk Parts / Suggested PO Qty",
        loading: "Updating data...",
        updated: "Updated",
        update_failed: "Update failed: ",
        no_risk_parts: "No risk parts currently",
        no_po_data: "No purchase recommendation data",
        part_no: "Part No.",
        suggested_po_qty: "Suggested PO Qty",
        first_shortage_date: "First Shortage Date",
        first_order_date: "Suggested Order Date",
        first_eta: "Required ETA",
        days_below_safety: "Days Below Safety",
        days_below_zero: "Days Below Zero",
        max_shortage_qty: "Max Shortage",
        min_available: "Min Available",
        original_demand_legend: "Forecast Demand",
        adjusted_demand_legend: "Expected Output",
        gap_legend: "Output Gap",
        temperature: "Temperature",
        vibration: "Vibration",
        health_score: "Health Score",
        suggested_po_legend: "Suggested PO Qty",
        compare_chart_title: "7-Day Demand / Output / Gap",
        iot_chart_title: "Machine Health Monitoring",
        po_chart_title: "Top 10 Recommended Purchase Parts"
    }
};

function applyLang() {
    const t = TEXT[LANG];
    document.getElementById("title").textContent = t.title;
    document.getElementById("label_updated_at").textContent = t.updated_at;
    document.getElementById("label_avg_health").textContent = t.avg_health;
    document.getElementById("label_min_health").textContent = t.min_health;
    document.getElementById("label_capacity_factor").textContent = t.capacity_factor;
    document.getElementById("label_original_qty").textContent = t.original_demand;
    document.getElementById("label_forecast_qty").textContent = t.adjusted_demand;
    document.getElementById("label_risk_po").textContent = t.risk_po;
    document.getElementById("label_risk_parts").textContent = t.risk_parts;
    document.getElementById("label_summary").textContent = t.summary;
    document.getElementById("label_po_table").textContent = t.po_table;
    document.getElementById("iot_chart_title_text").textContent = t.iot_chart_title;
}

function renderCompareChart() {
    if (!dashboardData) return;

    Plotly.react("compare_chart", [
        {
            x: dashboardData.charts.compare.x,
            y: dashboardData.charts.compare.demand,
            type: "bar",
            name: TEXT[LANG].original_demand_legend
        },
        {
            x: dashboardData.charts.compare.x,
            y: dashboardData.charts.compare.output,
            type: "bar",
            name: TEXT[LANG].adjusted_demand_legend
        },
        {
            x: dashboardData.charts.compare.x,
            y: dashboardData.charts.compare.gap,
            type: "scatter",
            mode: "lines+markers",
            name: TEXT[LANG].gap_legend
        }
    ], {
        title: TEXT[LANG].compare_chart_title,
        barmode: "group",
        template: "plotly_dark",
        height: 350,
        margin: { t: 50, l: 50, r: 20, b: 50 },
        paper_bgcolor: "#0f1b33",
        plot_bgcolor: "#0f1b33"
    }, { responsive: true });
}

function renderIotChart() {
    if (!dashboardData || !dashboardData.charts || !dashboardData.charts.iot) return;

    const machines = dashboardData.charts.iot.machines || {};
    const machineIds = dashboardData.charts.iot.machine_ids || [];

    if (!selectedMachine && machineIds.length > 0) {
        selectedMachine = machineIds[0];
    }

    const current = machines[selectedMachine];
    if (!current) {
        Plotly.react("iot_chart", [], {
            title: TEXT[LANG].iot_chart_title,
            template: "plotly_dark",
            height: 350,
            paper_bgcolor: "#0f1b33",
            plot_bgcolor: "#0f1b33"
        }, { responsive: true });
        return;
    }

    Plotly.react("iot_chart", [
        {
            x: current.x,
            y: current.temperature,
            type: "scatter",
            mode: "lines+markers",
            name: TEXT[LANG].temperature,
            yaxis: "y"
        },
        {
            x: current.x,
            y: current.vibration,
            type: "scatter",
            mode: "lines+markers",
            name: TEXT[LANG].vibration,
            yaxis: "y2"
        },
        {
            x: current.x,
            y: current.health_score,
            type: "scatter",
            mode: "lines+markers",
            name: TEXT[LANG].health_score,
            yaxis: "y3"
        }
    ], {
        title: `${TEXT[LANG].iot_chart_title} - ${selectedMachine}`,
        template: "plotly_dark",
        height: 350,
        margin: { t: 50, l: 50, r: 60, b: 50 },
        paper_bgcolor: "#0f1b33",
        plot_bgcolor: "#0f1b33",
        yaxis: { title: TEXT[LANG].temperature },
        yaxis2: {
            title: TEXT[LANG].vibration,
            overlaying: "y",
            side: "right"
        },
        yaxis3: {
            title: TEXT[LANG].health_score,
            overlaying: "y",
            side: "right",
            position: 0.93,
            range: [0, 1]
        }
    }, { responsive: true });
}

function renderPoChart() {
    if (!dashboardData) return;

    Plotly.react("po_chart", [
        {
            x: dashboardData.charts.po.labels,
            y: dashboardData.charts.po.values,
            type: "bar",
            name: TEXT[LANG].suggested_po_legend
        }
    ], {
        title: TEXT[LANG].po_chart_title,
        template: "plotly_dark",
        height: 350,
        margin: { t: 50, l: 50, r: 20, b: 50 },
        paper_bgcolor: "#0f1b33",
        plot_bgcolor: "#0f1b33"
    }, { responsive: true });
}

function setLang(lang) {
    LANG = lang;
    applyLang();

    if (dashboardData) {
        renderCompareChart();
        renderIotChart();
        renderPoChart();
        renderSummary();
        renderPoTable();
        renderRiskParts();
    }
}

function renderRiskParts() {
    const data = dashboardData;
    const riskBox = document.getElementById("risk_parts");
    if (data.risk_parts.length > 0) {
        riskBox.innerHTML = data.risk_parts.map(x => `<span class="tag danger">${x}</span>`).join("");
    } else {
        riskBox.innerHTML = `<span class="tag ok">${TEXT[LANG].no_risk_parts}</span>`;
    }
}

function renderSummary() {
    const data = dashboardData;
    if (LANG === "zh") {
        document.getElementById("summary_block").innerHTML = `
            <p>近 ${data.summary.lookback_days} 天歷史資料已補齊無訂單日後再進行需求預測，降低平均值高估風險。</p>
            <p>未來 ${data.summary.forecast_days} 天同時保留「預測需求」與「設備健康度修正後可執行產出」兩條邏輯。</p>
            <p>MRP 建議以下游需求日回推 lead time，避免把缺料日誤當成下單日。</p>
            <p>需求端零件總量：${data.summary.total_demand_part_qty}；可執行產出對應零件總量：${data.summary.total_output_part_qty}。</p>
            <p>建議採購品項數：${data.summary.po_count}。</p>
        `;
    } else {
        document.getElementById("summary_block").innerHTML = `
            <p>Historical demand is forecast after filling zero-order days, reducing upward bias in averages.</p>
            <p>The model separately keeps forecast demand and executable output adjusted by machine health.</p>
            <p>MRP suggestions are backward-scheduled from shortage date using lead time.</p>
            <p>Total parts for demand: ${data.summary.total_demand_part_qty}; total parts for executable output: ${data.summary.total_output_part_qty}.</p>
            <p>Suggested purchase items: ${data.summary.po_count}.</p>
        `;
    }
}

function renderPoTable() {
    const data = dashboardData;
    const tableRows = data.po_table.length > 0
        ? `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>${TEXT[LANG].part_no}</th>
                        <th>${TEXT[LANG].suggested_po_qty}</th>
                        <th>${TEXT[LANG].first_shortage_date}</th>
                        <th>${TEXT[LANG].first_order_date}</th>
                        <th>${TEXT[LANG].first_eta}</th>
                        <th>${TEXT[LANG].days_below_safety}</th>
                        <th>${TEXT[LANG].days_below_zero}</th>
                        <th>${TEXT[LANG].max_shortage_qty}</th>
                        <th>${TEXT[LANG].min_available}</th>
                    </tr>
                </thead>
                <tbody>
                    ${data.po_table.map(row => `
                        <tr>
                            <td>${row.part_no}</td>
                            <td>${row.total_recommended_qty}</td>
                            <td>${row.first_shortage_date}</td>
                            <td>${row.first_suggested_order_date}</td>
                            <td>${row.first_required_eta}</td>
                            <td>${row.days_below_safety}</td>
                            <td>${row.days_below_zero}</td>
                            <td>${row.max_shortage_qty}</td>
                            <td>${row.min_available}</td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        `
        : `<p>${TEXT[LANG].no_po_data}</p>`;

    document.getElementById("po_table").innerHTML = tableRows;
}

async function loadDashboard() {
    const status = document.getElementById("status_text");
    status.textContent = TEXT[LANG].loading;

    try {
        const res = await fetch("/api/dashboard?t=" + new Date().getTime());
        const data = await res.json();

        if (data.error) {
            document.body.innerHTML = `
                <div style="padding:40px;color:white;background:#081224;font-family:Arial;">
                    <h1>智慧製造 Dashboard</h1>
                    <p>${data.error}</p>
                </div>
            `;
            return;
        }

        dashboardData = data;

        document.getElementById("updated_at").textContent = data.updated_at;
        document.getElementById("avg_health").textContent = data.kpi.avg_health.toFixed(3);
        document.getElementById("min_health").textContent = data.kpi.min_health.toFixed(3);
        document.getElementById("capacity_factor").textContent = data.kpi.capacity_factor.toFixed(3);
        document.getElementById("total_original_qty").textContent = data.kpi.total_forecast_demand;
        document.getElementById("total_forecast_qty").textContent = data.kpi.total_expected_output;
        document.getElementById("risk_po").textContent = `${data.kpi.risk_count} / ${data.kpi.total_po_qty}`;

        const selector = document.getElementById("machine_selector");
        const machineIds = data.charts.iot.machine_ids || [];

        selector.innerHTML = machineIds.map(id => `<option value="${id}">${id}</option>`).join("");

        if (!selectedMachine || !machineIds.includes(selectedMachine)) {
            selectedMachine = machineIds.length > 0 ? machineIds[0] : null;
        }

        selector.value = selectedMachine || "";
        selector.onchange = function () {
            selectedMachine = this.value;
            renderIotChart();
        };

        renderRiskParts();
        renderSummary();
        renderPoTable();
        renderCompareChart();
        renderIotChart();
        renderPoChart();

        status.textContent = TEXT[LANG].updated;
    } catch (err) {
        console.error(err);
        status.textContent = TEXT[LANG].update_failed + err;
    }
}

applyLang();
loadDashboard();
setInterval(loadDashboard, 1000);