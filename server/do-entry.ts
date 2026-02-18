/**
 * DigitalOcean Deployment Entry Point
 * 
 * Replaces server/_core/index.ts for standalone deployment.
 * - No Manus OAuth (all routes are public)
 * - Uses email notifications instead of Forge API
 * - Connects to local MySQL instead of TiDB Cloud
 * 
 * Build: esbuild server/do-entry.ts --platform=node --packages=external --bundle --format=esm --outdir=dist
 * Run:   NODE_ENV=production node dist/do-entry.js
 */
import "dotenv/config";
import express from "express";
import { createServer } from "http";
import net from "net";
import path from "path";
import fs from "fs";
import { createExpressMiddleware } from "@trpc/server/adapters/express";
import { appRouter } from "./routers";
import type { TrpcContext } from "./_core/context";
import { startPipelineScheduler } from "./pipelineOrchestrator";

// ── Fake user context (no auth, single-owner dashboard) ──────────────
// All procedures get a fake "owner" user so protectedProcedure works
const OWNER_USER = {
  id: 1,
  openId: process.env.OWNER_OPEN_ID || "do-owner",
  name: process.env.OWNER_NAME || "Owner",
  email: null,
  loginMethod: "local",
  role: "admin" as const,
  createdAt: new Date(),
  updatedAt: new Date(),
  lastSignedIn: new Date(),
};

function createDoContext(opts: { req: express.Request; res: express.Response }): TrpcContext {
  return {
    req: opts.req,
    res: opts.res,
    user: OWNER_USER,
  };
}

// ── Port detection ───────────────────────────────────────────────────
function isPortAvailable(port: number): Promise<boolean> {
  return new Promise(resolve => {
    const server = net.createServer();
    server.listen(port, () => {
      server.close(() => resolve(true));
    });
    server.on("error", () => resolve(false));
  });
}

async function findAvailablePort(startPort: number = 3000): Promise<number> {
  for (let port = startPort; port < startPort + 20; port++) {
    if (await isPortAvailable(port)) return port;
  }
  throw new Error(`No available port found starting from ${startPort}`);
}

// ── Static file serving (production) ─────────────────────────────────
function serveStatic(app: express.Express) {
  const distPath = path.resolve(import.meta.dirname, "public");
  if (!fs.existsSync(distPath)) {
    console.error(`Could not find the build directory: ${distPath}, make sure to build the client first`);
  }
  app.use(express.static(distPath));
  app.use("*", (_req, res) => {
    res.sendFile(path.resolve(distPath, "index.html"));
  });
}

// ── Main ─────────────────────────────────────────────────────────────
async function startServer() {
  const app = express();
  const server = createServer(app);

  app.use(express.json({ limit: "50mb" }));
  app.use(express.urlencoded({ limit: "50mb", extended: true }));

  // Health check endpoint
  app.get("/api/health", (_req, res) => {
    res.json({ ok: true, timestamp: Date.now(), env: "digitalocean" });
  });

  // tRPC API — all procedures get the owner user context
  app.use(
    "/api/trpc",
    createExpressMiddleware({
      router: appRouter,
      createContext: createDoContext,
    })
  );

  // Serve static files in production
  if (process.env.NODE_ENV === "production") {
    serveStatic(app);
  } else {
    // In development, use Vite
    const { setupVite } = await import("./_core/vite");
    await setupVite(app, server);
  }

  const preferredPort = parseInt(process.env.PORT || "3000");
  const port = await findAvailablePort(preferredPort);

  if (port !== preferredPort) {
    console.log(`Port ${preferredPort} is busy, using port ${port} instead`);
  }

  server.listen(port, "0.0.0.0", () => {
    console.log(`[DO] Server running on http://0.0.0.0:${port}/`);
    console.log(`[DO] Environment: ${process.env.NODE_ENV || "development"}`);
    console.log(`[DO] Owner: ${OWNER_USER.name} (${OWNER_USER.openId})`);

    // Start pipeline scheduler
    startPipelineScheduler().catch(err => {
      console.error("[Pipeline] Failed to start scheduler:", err);
    });
  });
}

startServer().catch(console.error);
