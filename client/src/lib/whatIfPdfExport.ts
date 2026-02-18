/**
 * What-If Scenario PDF Export
 * Generates an institutional-quality PDF report with scenario parameters,
 * r* results, and sensitivity analysis.
 */
import { jsPDF } from 'jspdf';

interface WhatIfExportData {
  // Scenario info
  scenarioName: string;
  scenarioDescription: string;
  exportDate: string;

  // Variable values
  variables: Array<{
    label: string;
    value: number;
    unit: string;
    defaultValue: number;
    delta: number;
  }>;

  // Results
  results: {
    currentComposite: number;
    newComposite: number;
    deltaRstar: number;
    currentSelicStar: number;
    newSelicStar: number;
    deltaSelicStar: number;
    newFiscalRstar: number;
    currentFiscalRstar: number;
    newPolicyGap: number;
    signal: string;
  };

  // Current model info
  modelInfo: {
    runDate: string;
    currentRegime: string;
    selicTarget: number;
    spotRate: number;
    compositeMethod: string;
    activeModels: number;
  };

  // Monte Carlo results (optional)
  monteCarlo?: {
    simulations: number;
    mean: number;
    median: number;
    p5: number;
    p25: number;
    p75: number;
    p95: number;
    std: number;
    probAbove6: number;
    probBelow3: number;
  };
}

// ============================================================
// PDF Color Palette (Institutional Dark Theme)
// ============================================================
const C = {
  bg: [15, 23, 42] as [number, number, number],          // slate-900
  cardBg: [30, 41, 59] as [number, number, number],      // slate-800
  headerBg: [51, 65, 85] as [number, number, number],    // slate-700
  primary: [6, 182, 212] as [number, number, number],    // cyan-400
  accent: [139, 92, 246] as [number, number, number],    // violet-400
  green: [52, 211, 153] as [number, number, number],     // emerald-400
  amber: [251, 191, 36] as [number, number, number],     // amber-400
  rose: [244, 63, 94] as [number, number, number],       // rose-500
  text: [226, 232, 240] as [number, number, number],     // slate-200
  textMuted: [148, 163, 184] as [number, number, number], // slate-400
  textDim: [100, 116, 139] as [number, number, number],  // slate-500
  border: [51, 65, 85] as [number, number, number],      // slate-700
  white: [255, 255, 255] as [number, number, number],
};

function drawRoundedRect(doc: jsPDF, x: number, y: number, w: number, h: number, r: number, fill: [number, number, number]) {
  doc.setFillColor(...fill);
  doc.roundedRect(x, y, w, h, r, r, 'F');
}

function drawLine(doc: jsPDF, x1: number, y1: number, x2: number, y2: number, color: [number, number, number], width = 0.3) {
  doc.setDrawColor(...color);
  doc.setLineWidth(width);
  doc.line(x1, y1, x2, y2);
}

export function generateWhatIfPdf(data: WhatIfExportData) {
  const doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' });
  const pageW = 210;
  const pageH = 297;
  const margin = 15;
  const contentW = pageW - margin * 2;
  let y = 0;

  // ============================================================
  // Background
  // ============================================================
  doc.setFillColor(...C.bg);
  doc.rect(0, 0, pageW, pageH, 'F');

  // ============================================================
  // Header
  // ============================================================
  drawRoundedRect(doc, margin, 12, contentW, 28, 3, C.cardBg);

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(16);
  doc.setTextColor(...C.primary);
  doc.text('ARC MACRO', margin + 8, 24);

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(9);
  doc.setTextColor(...C.textMuted);
  doc.text('What-If Scenario Report', margin + 8, 31);

  // Right side: date and model info
  doc.setFontSize(8);
  doc.setTextColor(...C.textDim);
  doc.text(`Gerado: ${data.exportDate}`, pageW - margin - 8, 22, { align: 'right' });
  doc.text(`Modelo: ${data.modelInfo.runDate}`, pageW - margin - 8, 27, { align: 'right' });
  doc.text(`Regime: ${data.modelInfo.currentRegime}`, pageW - margin - 8, 32, { align: 'right' });

  y = 48;

  // ============================================================
  // Scenario Title
  // ============================================================
  drawRoundedRect(doc, margin, y, contentW, 14, 2, C.headerBg);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(10);
  doc.setTextColor(...C.white);
  doc.text(`Cenário: ${data.scenarioName}`, margin + 6, y + 6);
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(7.5);
  doc.setTextColor(...C.textMuted);
  doc.text(data.scenarioDescription, margin + 6, y + 11);

  y += 20;

  // ============================================================
  // Results Summary (Big Numbers)
  // ============================================================
  const resultBoxW = (contentW - 6) / 3;

  // r* Composto
  drawRoundedRect(doc, margin, y, resultBoxW, 30, 2, C.cardBg);
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(7);
  doc.setTextColor(...C.textDim);
  doc.text('r* Composto', margin + resultBoxW / 2, y + 6, { align: 'center' });
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(18);
  const rstarColor = data.results.newComposite > 5.5 ? C.amber : data.results.newComposite < 3.5 ? C.green : C.primary;
  doc.setTextColor(...rstarColor);
  doc.text(`${data.results.newComposite.toFixed(2)}%`, margin + resultBoxW / 2, y + 18, { align: 'center' });
  // Delta
  if (Math.abs(data.results.deltaRstar) > 0.01) {
    const deltaColor = data.results.deltaRstar > 0 ? C.amber : C.green;
    doc.setFontSize(8);
    doc.setTextColor(...deltaColor);
    const arrow = data.results.deltaRstar > 0 ? '+' : '';
    doc.text(`${arrow}${data.results.deltaRstar.toFixed(2)}pp`, margin + resultBoxW / 2, y + 25, { align: 'center' });
  }

  // SELIC*
  const x2 = margin + resultBoxW + 3;
  drawRoundedRect(doc, x2, y, resultBoxW, 30, 2, C.cardBg);
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(7);
  doc.setTextColor(...C.textDim);
  doc.text('SELIC*', x2 + resultBoxW / 2, y + 6, { align: 'center' });
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(18);
  doc.setTextColor(...C.text);
  doc.text(`${data.results.newSelicStar.toFixed(2)}%`, x2 + resultBoxW / 2, y + 18, { align: 'center' });
  if (Math.abs(data.results.deltaSelicStar) > 0.01) {
    const deltaColor = data.results.deltaSelicStar > 0 ? C.amber : C.green;
    doc.setFontSize(8);
    doc.setTextColor(...deltaColor);
    const arrow = data.results.deltaSelicStar > 0 ? '+' : '';
    doc.text(`${arrow}${data.results.deltaSelicStar.toFixed(2)}pp`, x2 + resultBoxW / 2, y + 25, { align: 'center' });
  }

  // Policy Gap
  const x3 = margin + (resultBoxW + 3) * 2;
  drawRoundedRect(doc, x3, y, resultBoxW, 30, 2, C.cardBg);
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(7);
  doc.setTextColor(...C.textDim);
  doc.text('Policy Gap', x3 + resultBoxW / 2, y + 6, { align: 'center' });
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(18);
  const gapColor = data.results.newPolicyGap > 1 ? C.amber : data.results.newPolicyGap < -1 ? C.green : C.text;
  doc.setTextColor(...gapColor);
  const gapSign = data.results.newPolicyGap > 0 ? '+' : '';
  doc.text(`${gapSign}${data.results.newPolicyGap.toFixed(2)}pp`, x3 + resultBoxW / 2, y + 18, { align: 'center' });
  doc.setFontSize(7);
  doc.setTextColor(...C.textDim);
  doc.text(`SELIC ${data.modelInfo.selicTarget.toFixed(1)}% - SELIC*`, x3 + resultBoxW / 2, y + 25, { align: 'center' });

  y += 36;

  // ============================================================
  // Signal Interpretation Bar
  // ============================================================
  const signalColor = data.results.signal === 'restrictive' ? C.amber :
    data.results.signal === 'accommodative' ? C.green : C.primary;
  const signalText = data.results.signal === 'restrictive' ? 'CENÁRIO RESTRITIVO — Prêmio fiscal elevado' :
    data.results.signal === 'accommodative' ? 'CENÁRIO ACOMODATÍCIO — Condições favoráveis' :
    'CENÁRIO NEUTRO — Equilíbrio macro';

  drawRoundedRect(doc, margin, y, contentW, 10, 2, C.cardBg);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(8);
  doc.setTextColor(...signalColor);
  doc.text(signalText, pageW / 2, y + 6.5, { align: 'center' });

  y += 16;

  // ============================================================
  // Variables Table
  // ============================================================
  drawRoundedRect(doc, margin, y, contentW, 8, 2, C.headerBg);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(8);
  doc.setTextColor(...C.white);
  doc.text('PARÂMETROS DO CENÁRIO', margin + 6, y + 5.5);
  y += 10;

  // Table header
  const cols = [margin + 4, margin + 60, margin + 90, margin + 120, margin + 150];
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(7);
  doc.setTextColor(...C.textDim);
  doc.text('Variável', cols[0], y + 4);
  doc.text('Atual', cols[1], y + 4);
  doc.text('Cenário', cols[2], y + 4);
  doc.text('Delta', cols[3], y + 4);
  doc.text('Impacto r*', cols[4], y + 4);
  y += 6;
  drawLine(doc, margin + 2, y, margin + contentW - 2, y, C.border);
  y += 2;

  // Table rows
  for (const v of data.variables) {
    drawRoundedRect(doc, margin + 1, y, contentW - 2, 7, 1, C.cardBg);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(7.5);
    doc.setTextColor(...C.text);
    doc.text(v.label, cols[0], y + 5);
    doc.text(`${v.defaultValue.toFixed(v.unit === '%' ? 1 : 0)}${v.unit}`, cols[1], y + 5);
    doc.text(`${v.value.toFixed(v.unit === '%' ? 1 : 0)}${v.unit}`, cols[2], y + 5);

    const deltaStr = `${v.delta > 0 ? '+' : ''}${v.delta.toFixed(v.unit === '%' ? 1 : 0)}${v.unit}`;
    const deltaColor = Math.abs(v.delta) < 0.01 ? C.textDim : (v.delta > 0 ? C.amber : C.green);
    doc.setTextColor(...deltaColor);
    doc.text(deltaStr, cols[3], y + 5);

    doc.setTextColor(...C.textMuted);
    doc.text('—', cols[4], y + 5);
    y += 8;
  }

  y += 6;

  // ============================================================
  // Comparison Table (Current vs Scenario)
  // ============================================================
  drawRoundedRect(doc, margin, y, contentW, 8, 2, C.headerBg);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(8);
  doc.setTextColor(...C.white);
  doc.text('COMPARAÇÃO: ATUAL vs CENÁRIO', margin + 6, y + 5.5);
  y += 10;

  const compRows = [
    { label: 'r* Composto (real)', current: data.results.currentComposite, scenario: data.results.newComposite, unit: '%' },
    { label: 'r* Fiscal', current: data.results.currentFiscalRstar, scenario: data.results.newFiscalRstar, unit: '%' },
    { label: 'SELIC* (nominal)', current: data.results.currentSelicStar, scenario: data.results.newSelicStar, unit: '%' },
    { label: 'Policy Gap', current: data.modelInfo.selicTarget - data.results.currentSelicStar, scenario: data.results.newPolicyGap, unit: 'pp' },
  ];

  const compCols = [margin + 4, margin + 70, margin + 110, margin + 145];
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(7);
  doc.setTextColor(...C.textDim);
  doc.text('Métrica', compCols[0], y + 4);
  doc.text('Atual', compCols[1], y + 4);
  doc.text('Cenário', compCols[2], y + 4);
  doc.text('Δ', compCols[3], y + 4);
  y += 6;
  drawLine(doc, margin + 2, y, margin + contentW - 2, y, C.border);
  y += 2;

  for (const row of compRows) {
    drawRoundedRect(doc, margin + 1, y, contentW - 2, 7, 1, C.cardBg);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(7.5);
    doc.setTextColor(...C.text);
    doc.text(row.label, compCols[0], y + 5);
    doc.text(`${row.current.toFixed(2)}${row.unit}`, compCols[1], y + 5);

    doc.setFont('helvetica', 'bold');
    doc.setTextColor(...C.primary);
    doc.text(`${row.scenario.toFixed(2)}${row.unit}`, compCols[2], y + 5);

    const delta = row.scenario - row.current;
    const dColor = Math.abs(delta) < 0.01 ? C.textDim : (delta > 0 ? C.amber : C.green);
    doc.setTextColor(...dColor);
    doc.text(`${delta > 0 ? '+' : ''}${delta.toFixed(2)}`, compCols[3], y + 5);
    y += 8;
  }

  y += 6;

  // ============================================================
  // Monte Carlo Section (if available)
  // ============================================================
  if (data.monteCarlo) {
    const mc = data.monteCarlo;

    drawRoundedRect(doc, margin, y, contentW, 8, 2, C.headerBg);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(8);
    doc.setTextColor(...C.white);
    doc.text(`SIMULAÇÃO MONTE CARLO (${mc.simulations.toLocaleString()} simulações)`, margin + 6, y + 5.5);
    y += 10;

    // Stats grid
    const mcBoxW = (contentW - 9) / 4;
    const mcStats = [
      { label: 'Média', value: `${mc.mean.toFixed(2)}%`, color: C.primary },
      { label: 'Mediana', value: `${mc.median.toFixed(2)}%`, color: C.text },
      { label: 'Desvio Padrão', value: `${mc.std.toFixed(2)}pp`, color: C.accent },
      { label: 'P(r*>6%)', value: `${(mc.probAbove6 * 100).toFixed(1)}%`, color: mc.probAbove6 > 0.3 ? C.rose : C.green },
    ];

    mcStats.forEach((stat, i) => {
      const bx = margin + i * (mcBoxW + 3);
      drawRoundedRect(doc, bx, y, mcBoxW, 18, 2, C.cardBg);
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(6.5);
      doc.setTextColor(...C.textDim);
      doc.text(stat.label, bx + mcBoxW / 2, y + 5, { align: 'center' });
      doc.setFont('helvetica', 'bold');
      doc.setFontSize(12);
      doc.setTextColor(...stat.color);
      doc.text(stat.value, bx + mcBoxW / 2, y + 13.5, { align: 'center' });
    });

    y += 22;

    // Percentile table
    const pctCols = [margin + 4, margin + 35, margin + 60, margin + 85, margin + 110, margin + 135];
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(7);
    doc.setTextColor(...C.textDim);
    ['Percentil', 'P5', 'P25', 'P50', 'P75', 'P95'].forEach((h, i) => {
      doc.text(h, pctCols[i], y + 4);
    });
    y += 6;
    drawLine(doc, margin + 2, y, margin + contentW - 2, y, C.border);
    y += 2;

    drawRoundedRect(doc, margin + 1, y, contentW - 2, 7, 1, C.cardBg);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(7.5);
    doc.setTextColor(...C.text);
    doc.text('r* (%)', pctCols[0], y + 5);
    [mc.p5, mc.p25, mc.median, mc.p75, mc.p95].forEach((v, i) => {
      doc.text(v.toFixed(2), pctCols[i + 1], y + 5);
    });
    y += 12;
  }

  // ============================================================
  // Footer
  // ============================================================
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(6.5);
  doc.setTextColor(...C.textDim);
  doc.text('ARC Macro v3.9.1 — FX + Rates + Sovereign', margin, pageH - 12);
  doc.text('Este relatório é gerado automaticamente e não constitui recomendação de investimento.', margin, pageH - 8);
  doc.text(`SPOT: ${data.modelInfo.spotRate.toFixed(4)} | SELIC: ${data.modelInfo.selicTarget.toFixed(1)}% | ${data.modelInfo.activeModels} modelos ativos`, pageW - margin, pageH - 12, { align: 'right' });

  drawLine(doc, margin, pageH - 15, pageW - margin, pageH - 15, C.border);

  // Save
  const filename = `rstar_whatif_${data.scenarioName.toLowerCase().replace(/\s+/g, '_')}_${data.exportDate.replace(/[/\s:]/g, '-')}.pdf`;
  doc.save(filename);
}

export type { WhatIfExportData };
