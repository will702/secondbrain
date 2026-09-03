#!/usr/bin/env node

import { exec, spawn } from "child_process";
import net from "net";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..");
const ENV_PATH = `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${process.env.PATH || ""}`;

function isPortOpen(port, host = "127.0.0.1", timeoutMs = 1500) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    socket.setTimeout(timeoutMs);
    socket.once("connect", () => {
      socket.destroy();
      resolve(true);
    });
    socket.once("timeout", () => {
      socket.destroy();
      resolve(false);
    });
    socket.once("error", () => {
      resolve(false);
    });
    socket.connect(port, host);
  });
}

async function isApiHealthy() {
  try {
    const res = await fetch("http://127.0.0.1:8000/healthz", {
      signal: AbortSignal.timeout(2000),
    });
    if (!res.ok) return false;
    const data = await res.json();
    return data.status === "ok";
  } catch {
    return false;
  }
}

async function isLocalAiRunning() {
  try {
    const res = await fetch("http://127.0.0.1:8080/health", {
      signal: AbortSignal.timeout(1500),
    });
    return res.ok;
  } catch {
    return false;
  }
}

async function isWorkersRunning() {
  return new Promise((resolve) => {
    exec('pgrep -f "app.workers.runner"', { env: { ...process.env, PATH: ENV_PATH } }, (err, stdout) => {
      resolve(!err && !!stdout.trim());
    });
  });
}

async function main() {
  console.log("\n\x1b[1m\x1b[33m%s\x1b[0m", "==================================================");
  console.log("\x1b[1m\x1b[33m%s\x1b[0m", " 🧠  SECOND BRAIN OS — FULL SYSTEM STARTUP ");
  console.log("\x1b[1m\x1b[33m%s\x1b[0m", "==================================================\n");

  // 1. Database Check & Start
  const dbRunning = await isPortOpen(5433);
  if (!dbRunning) {
    process.stdout.write("  ⏳ Starting PostgreSQL + pgvector container… ");
    await new Promise((resolve, reject) => {
      exec("docker compose up -d", { cwd: REPO_ROOT, env: { ...process.env, PATH: ENV_PATH } }, (err) => {
        if (err) reject(err);
        else resolve();
      });
    });

    let ready = false;
    for (let i = 0; i < 20; i++) {
      if (await isPortOpen(5433)) {
        ready = true;
        break;
      }
      await new Promise((r) => setTimeout(r, 600));
    }
    if (ready) {
      console.log("\x1b[32m%s\x1b[0m", "✓ Ready (port 5433)");
    } else {
      throw new Error("Timed out waiting for PostgreSQL on port 5433");
    }
  } else {
    console.log("  \x1b[32m✓\x1b[0m Database running (port 5433)");
  }

  // 2. Local AI Server Check & Start
  const aiRunning = await isLocalAiRunning();
  if (!aiRunning) {
    process.stdout.write("  ⏳ Starting local AI engine (embeddings & LLM)… ");
    exec("local-ai serve > /dev/null 2>&1 &", { env: { ...process.env, PATH: ENV_PATH } });
    let aiReady = false;
    for (let i = 0; i < 20; i++) {
      if (await isLocalAiRunning()) {
        aiReady = true;
        break;
      }
      await new Promise((r) => setTimeout(r, 500));
    }
    if (aiReady) {
      console.log("\x1b[32m%s\x1b[0m", "✓ Online (http://127.0.0.1:8080)");
    } else {
      console.log("\x1b[33m%s\x1b[0m", "! Initializing in background");
    }
  } else {
    console.log("  \x1b[32m✓\x1b[0m Local AI engine online (http://127.0.0.1:8080)");
  }

  // 3. Database Migrations
  const apiDir = path.join(REPO_ROOT, "apps/api");
  process.stdout.write("  ⏳ Verifying database migrations… ");
  await new Promise((resolve, reject) => {
    exec("uv run alembic upgrade head", { cwd: apiDir, env: { ...process.env, PATH: ENV_PATH } }, (error) => {
      if (error) reject(error);
      else resolve();
    });
  });
  console.log("\x1b[32m%s\x1b[0m", "✓ Up to date");

  // 3. API Server Check & Start
  const apiHealthy = await isApiHealthy();
  if (!apiHealthy) {
    process.stdout.write("  ⏳ Starting FastAPI server on port 8000… ");
    const apiProc = spawn("uv", ["run", "uvicorn", "app.main:app", "--reload", "--port", "8000"], {
      cwd: apiDir,
      detached: true,
      stdio: "ignore",
      env: { ...process.env, PATH: ENV_PATH },
    });
    apiProc.unref();

    let apiReady = false;
    for (let i = 0; i < 25; i++) {
      if (await isApiHealthy()) {
        apiReady = true;
        break;
      }
      await new Promise((r) => setTimeout(r, 500));
    }
    if (apiReady) {
      console.log("\x1b[32m%s\x1b[0m", "✓ Online (http://127.0.0.1:8000)");
    } else {
      throw new Error("Timed out waiting for the API on port 8000");
    }
  } else {
    console.log("  \x1b[32m✓\x1b[0m FastAPI server online (http://127.0.0.1:8000)");
  }

  // 4. Background Workers Check & Start
  const workersActive = await isWorkersRunning();
  if (!workersActive) {
    process.stdout.write("  ⏳ Starting background intelligence workers… ");
    const workerProc = spawn("uv", ["run", "python", "-m", "app.workers.runner"], {
      cwd: apiDir,
      detached: true,
      stdio: "ignore",
      env: { ...process.env, PATH: ENV_PATH },
    });
    workerProc.unref();
    console.log("\x1b[32m%s\x1b[0m", "✓ Active");
  } else {
    console.log("  \x1b[32m✓\x1b[0m Background workers active");
  }

  // 5. Start Web Interface
  const webDir = path.join(REPO_ROOT, "apps/web");
  console.log("\n\x1b[32m%s\x1b[0m", "✨ All core systems active!");
  console.log("🌐 Starting Next.js Web Interface on \x1b[1mhttp://localhost:3000\x1b[0m\n");

  const webProc = spawn("pnpm", ["dev"], {
    cwd: webDir,
    stdio: "inherit",
    env: { ...process.env, PATH: ENV_PATH },
  });

  // Automatically open browser on macOS after short delay
  setTimeout(() => {
    exec("open http://localhost:3000", { env: { ...process.env, PATH: ENV_PATH } });
  }, 1500);

  webProc.on("exit", (code) => {
    process.exit(code || 0);
  });
}

main().catch((err) => {
  console.error("Error starting Second Brain OS:", err);
  process.exit(1);
});
