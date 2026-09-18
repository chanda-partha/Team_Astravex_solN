// GridWise AI Operator Frontend JavaScript Application

let sampleCasesMap = {};
let currentHours = [];

document.addEventListener("DOMContentLoaded", () => {
  checkBackendHealth();
  loadSampleCases();
  setupEventListeners();
});

async function checkBackendHealth() {
  const badge = document.getElementById("api-status-badge");
  try {
    const res = await fetch("/health");
    if (res.ok) {
      badge.innerHTML = '<span class="dot"></span> Backend: Online (200)';
    } else {
      badge.innerHTML = '⚠️ Backend: Error ' + res.status;
      badge.style.color = '#f87171';
    }
  } catch (err) {
    badge.innerHTML = '⚠️ Backend: Offline';
    badge.style.color = '#f87171';
  }
}

async function loadSampleCases() {
  try {
    const res = await fetch("/samples/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json");
    if (!res.ok) return;
    const data = await res.json();
    if (data.cases) {
      data.cases.forEach(c => {
        sampleCasesMap[c.id] = c;
      });
      // Populate selector on startup
      onSelectSample("SAMPLE-01");
    }
  } catch (err) {
    console.log("Using default fallback sample data");
  }
}

function setupEventListeners() {
  document.getElementById("sample-selector").addEventListener("change", (e) => {
    onSelectSample(e.target.value);
  });

  document.getElementById("btn-optimize").addEventListener("click", () => {
    generatePlan();
  });
}

function onSelectSample(sampleId) {
  const caseObj = sampleCasesMap[sampleId];
  if (!caseObj) return;

  const input = caseObj.input;
  
  // Set Operator Notes
  if (input.operator_notes) {
    document.getElementById("operator-notes-input").value = input.operator_notes.join("\n");
  }

  // Set Battery Specs
  if (input.battery) {
    document.getElementById("bat-capacity").value = input.battery.capacity_kwh;
    document.getElementById("bat-initial").value = input.battery.initial_energy_kwh;
    document.getElementById("bat-minimum").value = input.battery.minimum_energy_kwh;
    document.getElementById("bat-max-ch").value = input.battery.max_charge_kwh_per_hour;
    document.getElementById("bat-max-dis").value = input.battery.max_discharge_kwh_per_hour;
  }

  // Set Hours data
  if (input.hours) {
    currentHours = input.hours;
  }
}

function insertTemplate(type) {
  const textarea = document.getElementById("operator-notes-input");
  let text = "";
  if (type === 'solar') text = "Facilities will wash rooftop solar panels from 1 PM to 3 PM. Usable solar drop to 20%.";
  if (type === 'nocharge') text = "Battery charger isolated between 2 AM and 5 AM for electrical maintenance.";
  if (type === 'nodischarge') text = "Inverter test: do not discharge battery from 5 PM to 7 PM.";
  if (type === 'reserve') text = "Keep at least 60 kWh in storage between 6 PM and 9 PM for emergency reserve.";
  if (type === 'maxgrid') text = "Grid import must not exceed 155 kWh from 6 PM until 9 PM.";

  if (textarea.value.trim() === "") {
    textarea.value = text;
  } else {
    textarea.value += "\n" + text;
  }
}

function buildDefaultHours() {
  const hours = [];
  for (let h = 0; h < 24; h++) {
    const tariff = (h >= 17 && h <= 21) ? 15.0 : 5.0;
    const solar = (h >= 10 && h <= 15) ? 20.0 : 0.0;
    hours.push({
      hour: h,
      demand_kwh: 30.0,
      solar_kwh: solar,
      tariff_bdt_per_kwh: tariff
    });
  }
  return hours;
}

async function generatePlan() {
  const btn = document.getElementById("btn-optimize");
  const spinner = document.getElementById("opt-spinner");
  const errBanner = document.getElementById("error-banner");

  errBanner.classList.add("hidden");
  btn.disabled = true;
  spinner.classList.remove("hidden");

  // Build Payload
  const notesText = document.getElementById("operator-notes-input").value.trim();
  const notes = notesText.split("\n").map(n => n.trim()).filter(n => n.length > 0);

  if (notes.length === 0) {
    showError("Please enter at least one operator note.");
    btn.disabled = false;
    spinner.classList.add("hidden");
    return;
  }

  const sampleId = document.getElementById("sample-selector").value;
  const hoursData = (currentHours && currentHours.length === 24) ? currentHours : buildDefaultHours();

  const batteryData = {
    capacity_kwh: parseFloat(document.getElementById("bat-capacity").value),
    initial_energy_kwh: parseFloat(document.getElementById("bat-initial").value),
    minimum_energy_kwh: parseFloat(document.getElementById("bat-minimum").value),
    max_charge_kwh_per_hour: parseFloat(document.getElementById("bat-max-ch").value),
    max_discharge_kwh_per_hour: parseFloat(document.getElementById("bat-max-dis").value)
  };

  const payload = {
    scenario_id: sampleId !== "custom" ? sampleId : "DEMO-CUSTOM",
    operator_notes: notes.slice(0, 3), // Max 3 notes
    hours: hoursData,
    battery: batteryData
  };

  try {
    const res = await fetch("/optimize-energy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const data = await res.json();

    if (!res.ok) {
      showError(`API Error (${res.status}): ${data.detail || data.error || 'Optimization request failed'}`);
      btn.disabled = false;
      spinner.classList.add("hidden");
      return;
    }

    renderResults(data);

  } catch (err) {
    showError("Network or server connection failed: " + err.message);
  } finally {
    btn.disabled = false;
    spinner.classList.add("hidden");
  }
}

function showError(msg) {
  const errBanner = document.getElementById("error-banner");
  errBanner.innerText = msg;
  errBanner.classList.remove("hidden");
}

function renderResults(data) {
  // 1. Update KPI Cards
  document.getElementById("kpi-grid").innerHTML = `${data.total_grid_kwh.toFixed(1)} <span class="unit">kWh</span>`;
  document.getElementById("kpi-cost").innerHTML = `৳${data.total_cost_bdt.toFixed(2)} <span class="unit">BDT</span>`;
  document.getElementById("kpi-peak").innerHTML = `${data.peak_grid_kwh.toFixed(1)} <span class="unit">kWh/h</span>`;

  const appliedCount = data.directive_interpretation.filter(d => d.applies).length;
  document.getElementById("kpi-directives").innerHTML = `${appliedCount} <span class="unit">active</span>`;
  document.getElementById("kpi-model").innerText = `Scenario: ${data.scenario_id}`;

  // 2. Summary Box
  document.getElementById("summary-text").innerText = data.plan_summary || "24-hour optimal schedule generated and validated.";

  // 3. Render Directive Cards
  renderDirectives(data.directive_interpretation);

  // 4. Render Visual SVG Chart
  renderChart(data.hourly_plan);

  // 5. Render Schedule Table
  renderTable(data.hourly_plan);
}

function renderDirectives(directives) {
  const container = document.getElementById("directives-container");
  container.innerHTML = "";

  directives.forEach(d => {
    const card = document.createElement("div");
    card.className = `directive-card ${d.applies ? 'active' : 'no-op'}`;

    let adjStr = "";
    if (d.structured_adjustment) {
      adjStr = `Hours: [${d.structured_adjustment.hours.join(", ")}]`;
      if (d.structured_adjustment.factor !== undefined) adjStr += ` | Factor: ${d.structured_adjustment.factor}`;
      if (d.structured_adjustment.minimum_energy_kwh !== undefined) adjStr += ` | Reserve: ${d.structured_adjustment.minimum_energy_kwh} kWh`;
      if (d.structured_adjustment.max_grid_kwh !== undefined) adjStr += ` | Cap: ${d.structured_adjustment.max_grid_kwh} kWh`;
    }

    card.innerHTML = `
      <div class="directive-header">
        <span class="directive-type-tag">[Note ${d.note_index}] ${d.directive_type}</span>
        <span class="badge-tag ${d.applies ? 'applied' : 'noop'}">${d.applies ? 'APPLIED' : 'NO-OP'}</span>
      </div>
      ${adjStr ? `<div style="font-size:12px; font-family:var(--font-mono); color:var(--text-main); margin:4px 0;">${adjStr}</div>` : ''}
      <div class="directive-explanation">${d.explanation}</div>
    `;
    container.appendChild(card);
  });
}

function renderChart(plan) {
  const svg = document.getElementById("schedule-chart");
  svg.innerHTML = "";

  const width = 800;
  const height = 240;
  const padding = 30;

  const maxVal = Math.max(...plan.map(p => Math.max(p.grid_kwh, p.solar_used_kwh, p.battery_energy_after_kwh, 35)));
  
  const stepX = (width - padding * 2) / 23;

  // Background Grid Lines
  for (let i = 0; i <= 4; i++) {
    const y = padding + (height - padding * 2) * (i / 4);
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", padding);
    line.setAttribute("y1", y);
    line.setAttribute("x2", width - padding);
    line.setAttribute("y2", y);
    line.setAttribute("stroke", "rgba(255, 255, 255, 0.05)");
    svg.appendChild(line);
  }

  // Draw Grid Bars
  plan.forEach((p, i) => {
    const x = padding + i * stepX;
    const barW = stepX * 0.6;
    
    // Grid bar (blue)
    const gridH = (p.grid_kwh / maxVal) * (height - padding * 2);
    const rectGrid = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rectGrid.setAttribute("x", x - barW / 2);
    rectGrid.setAttribute("y", height - padding - gridH);
    rectGrid.setAttribute("width", barW);
    rectGrid.setAttribute("height", gridH);
    rectGrid.setAttribute("fill", "#3b82f6");
    rectGrid.setAttribute("rx", "2");
    svg.appendChild(rectGrid);

    // Solar bar overlay (amber)
    const solarH = (p.solar_used_kwh / maxVal) * (height - padding * 2);
    if (solarH > 0) {
      const rectSolar = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rectSolar.setAttribute("x", x - barW / 4);
      rectSolar.setAttribute("y", height - padding - solarH);
      rectSolar.setAttribute("width", barW / 2);
      rectSolar.setAttribute("height", solarH);
      rectSolar.setAttribute("fill", "#f59e0b");
      rectSolar.setAttribute("rx", "1");
      svg.appendChild(rectSolar);
    }
  });

  // Polyline for Battery Level (green line)
  const pts = plan.map((p, i) => {
    const x = padding + i * stepX;
    const y = height - padding - (p.battery_energy_after_kwh / maxVal) * (height - padding * 2);
    return `${x},${y}`;
  }).join(" ");

  const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  polyline.setAttribute("points", pts);
  polyline.setAttribute("fill", "none");
  polyline.setAttribute("stroke", "#10b981");
  polyline.setAttribute("stroke-width", "3");
  svg.appendChild(polyline);
}

function renderTable(plan) {
  const tbody = document.getElementById("schedule-tbody");
  tbody.innerHTML = "";

  plan.forEach(p => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>H${p.hour.toString().padStart(2, '0')}</td>
      <td>30.0</td>
      <td>${p.solar_used_kwh.toFixed(1)}</td>
      <td>${p.grid_kwh.toFixed(1)}</td>
      <td><span class="action-pill ${p.battery_action}">${p.battery_action.toUpperCase()}</span></td>
      <td>${p.battery_kwh.toFixed(1)}</td>
      <td>${p.battery_energy_after_kwh.toFixed(1)}</td>
    `;
    tbody.appendChild(tr);
  });
}
