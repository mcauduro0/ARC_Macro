import { COOKIE_NAME } from "@shared/const";
import { getSessionCookieOptions } from "./_core/cookies";
import { systemRouter } from "./_core/systemRouter";
import { publicProcedure, protectedProcedure, router } from "./_core/trpc";
import { getLatestModelRun, getModelRunHistory } from "./db";
import { executeModel, isModelRunning } from "./modelRunner";
import { portfolioRouter } from "./portfolioRouter";
import { getModelChangelog, getModelAlerts, getUnreadAlertCount, markModelAlertRead, dismissModelAlert, dismissAllModelAlerts, generatePostRunAlerts } from "./alertEngine";
import { notifyOwner } from "./_core/notification";
import { executePipeline, getPipelineStatus, getPipelineHistory, getLatestPipelineRun } from "./pipelineOrchestrator";
import { checkAllDataSources, getDataSourceHealthStatus } from "./dataSourceHealth";
import { z } from "zod";

export const appRouter = router({
  system: systemRouter,
  auth: router({
    me: publicProcedure.query(opts => opts.ctx.user),
    logout: publicProcedure.mutation(({ ctx }) => {
      const cookieOptions = getSessionCookieOptions(ctx.req);
      ctx.res.clearCookie(COOKIE_NAME, { ...cookieOptions, maxAge: -1 });
      return { success: true } as const;
    }),
  }),

  model: router({
    /**
     * Get the latest ARC Macro data (cross-asset dashboard).
     * Returns full dashboard JSON + timeseries + regime + state variables.
     * Falls back to embedded data if no DB run exists.
     */
    latest: publicProcedure.query(async () => {
      const run = await getLatestModelRun();

      if (run) {
        // Normalize dashboard data
        const dash = run.dashboardJson as Record<string, unknown>;

        // Normalize stress_tests: Python outputs dict {"2013_Taper": {...}} → convert to array
        const riskMetrics = dash?.risk_metrics as Record<string, unknown> | undefined;
        if (riskMetrics?.stress_tests && !Array.isArray(riskMetrics.stress_tests)) {
          const stDict = riskMetrics.stress_tests as Record<string, Record<string, unknown>>;
          riskMetrics.stress_tests = Object.entries(stDict).map(([key, val]) => ({
            name: key.replace(/_/g, ' ').replace(/^(\d{4})\s/, '$1 '),
            return_pct: (val.total_return as number) || 0,
            max_dd_pct: (val.max_drawdown as number) || 0,
            per_asset: val.asset_returns || {},
            start: val.start,
            end: val.end,
            months: val.months,
          }));
        }

        // Normalize regime_probabilities: Python outputs {"P_Carry": 0.76, ...} → keep as-is but ensure consistent keys
        const regimeProbs = dash?.regime_probabilities as Record<string, number> | undefined;
        if (regimeProbs) {
          // Ensure frontend-friendly keys
          if (regimeProbs.P_Carry !== undefined && regimeProbs.carry === undefined) {
            (regimeProbs as any).carry = regimeProbs.P_Carry;
            (regimeProbs as any).riskoff = regimeProbs.P_RiskOff || 0;
            (regimeProbs as any).stress_dom = regimeProbs.P_StressDom || 0;
          }
        }

        return {
          source: "database" as const,
          runDate: run.runDate,
          updatedAt: run.createdAt,
          dashboard: dash,
          timeseries: run.timeseriesJson,
          regime: run.regimeJson,
          cyclical: run.cyclicalJson,
          stateVariables: run.stateVariablesJson || [],
          score: run.scoreJson || [],
          backtest: run.backtestJson || null,
          shapImportance: run.shapJson || null,
          shapHistory: run.shapHistoryJson || null,
          // Legacy data for backward compatibility
          legacyDashboard: run.legacyDashboardJson,
          legacyTimeseries: run.legacyTimeseriesJson,
          legacyRegime: run.legacyRegimeJson,
          legacyCyclical: run.legacyCyclicalJson,
        };
      }

      return {
        source: "embedded" as const,
        runDate: null,
        updatedAt: null,
        dashboard: null,
        timeseries: null,
        regime: null,
        cyclical: null,
        stateVariables: null,
        score: null,
        backtest: null,
        shapImportance: null,
        shapHistory: null,
        legacyDashboard: null,
        legacyTimeseries: null,
        legacyRegime: null,
        legacyCyclical: null,
      };
    }),

    /**
     * Get model run history
     */
    history: publicProcedure.query(async () => {
      return getModelRunHistory(30);
    }),

    /**
     * Get model status (is it running?)
     */
    status: publicProcedure.query(() => {
      return {
        isRunning: isModelRunning(),
      };
    }),

    /**
     * Trigger a new model run (admin only)
     */
    run: protectedProcedure.mutation(async () => {
      if (isModelRunning()) {
        return { success: false, error: "Model is already running" };
      }

      // Run in background
      executeModel().catch(err => {
        console.error("[ModelRunner] Background run failed:", err);
      });

      return { success: true, message: "ARC Macro execution started" };
    }),
  }),

  portfolio: portfolioRouter,

  // ============================================================
  // Pipeline (Daily Automated Update)
  // ============================================================

  pipeline: router({
    /** Get current pipeline execution status (real-time) */
    status: publicProcedure.query(() => {
      return getPipelineStatus();
    }),

    /** Get pipeline run history */
    history: publicProcedure.query(async () => {
      return getPipelineHistory(20);
    }),

    /** Get the latest pipeline run */
    latest: publicProcedure.query(async () => {
      return getLatestPipelineRun();
    }),

    /** Trigger a full pipeline run (admin only) */
    trigger: protectedProcedure.mutation(async ({ ctx }) => {
      const userName = ctx.user?.name || ctx.user?.openId || 'unknown';
      
      // Run in background
      executePipeline("manual", userName).catch(err => {
        console.error("[Pipeline] Background run failed:", err);
      });

      return { success: true, message: "Pipeline di\u00e1rio iniciado" };
    }),
  }),

  // ============================================================
  // Model Changelog & Alerts
  // ============================================================

  changelog: router({
    /** Get model version history with metrics */
    list: publicProcedure.query(async () => {
      return getModelChangelog(50);
    }),
  }),

  // ============================================================
  // Data Source Health
  // ============================================================

  dataHealth: router({
    /** Get latest health status from DB (fast, no live check) */
    status: publicProcedure.query(async () => {
      return getDataSourceHealthStatus();
    }),

    /** Run live health checks on all data sources (slower, updates DB) */
    check: protectedProcedure.mutation(async () => {
      const results = await checkAllDataSources();
      return results;
    }),
  }),

  alerts: router({
    /** Get active model alerts */
    list: publicProcedure.query(async () => {
      return getModelAlerts(100, true);
    }),

    /** Get unread alert count (for notification badge) */
    unreadCount: publicProcedure.query(async () => {
      return getUnreadAlertCount();
    }),

    /** Mark an alert as read */
    markRead: protectedProcedure
      .input(z.object({ alertId: z.number() }))
      .mutation(async ({ input }) => {
        await markModelAlertRead(input.alertId);
        return { success: true };
      }),

    /** Dismiss an alert */
    dismiss: protectedProcedure
      .input(z.object({ alertId: z.number() }))
      .mutation(async ({ input }) => {
        await dismissModelAlert(input.alertId);
        return { success: true };
      }),

    /** Dismiss all alerts */
    dismissAll: protectedProcedure
      .mutation(async () => {
        await dismissAllModelAlerts();
        return { success: true };
      }),
    /** Test push notification (owner only) */
    testNotification: protectedProcedure
      .mutation(async () => {
        const success = await notifyOwner({
          title: '🔔 Teste de Notificação — ARC Macro',
          content: 'Esta é uma notificação de teste do sistema de alertas. Se você está recebendo esta mensagem, as notificações push estão funcionando corretamente.\n\nAlertas automáticos incluem:\n• Mudanças de regime (carry → risk-off)\n• Drawdown > -5%\n• Reversão de direção do score\n• Mudanças em SHAP features\n• Desvios de rebalanceamento',
        });
        return { success, message: success ? 'Notificação enviada com sucesso' : 'Falha ao enviar notificação' };
      }),
  }),
});

export type AppRouter = typeof appRouter;
