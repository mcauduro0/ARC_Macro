import { COOKIE_NAME } from "@shared/const";
import { getSessionCookieOptions } from "./_core/cookies";
import { systemRouter } from "./_core/systemRouter";
import { publicProcedure, protectedProcedure, router } from "./_core/trpc";
import { getLatestModelRun, getModelRunHistory } from "./db";
import { executeModel, isModelRunning } from "./modelRunner";

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
     * Get the latest Macro Risk OS data (cross-asset dashboard).
     * Returns full dashboard JSON + timeseries + regime + state variables.
     * Falls back to embedded data if no DB run exists.
     */
    latest: publicProcedure.query(async () => {
      const run = await getLatestModelRun();

      if (run) {
        return {
          source: "database" as const,
          runDate: run.runDate,
          updatedAt: run.createdAt,
          dashboard: run.dashboardJson,
          timeseries: run.timeseriesJson,
          regime: run.regimeJson,
          cyclical: run.cyclicalJson,
          stateVariables: run.stateVariablesJson || [],
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

      return { success: true, message: "Macro Risk OS execution started" };
    }),
  }),
});

export type AppRouter = typeof appRouter;
