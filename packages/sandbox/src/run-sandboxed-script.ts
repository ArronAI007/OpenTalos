import { GenericContainer } from "testcontainers";

export interface SandboxExecutionRequest {
  /** Absolute host path to the script file. Mounted read-only into the container — never copied
   * into a mutable location the script itself could tamper with. */
  scriptHostPath: string;
  args: string[];
  /** Written to a fixed in-container path (SANDBOX_INPUT_PATH) before the script runs. A script
   * that wants this input reads that file itself — there is no stdin piping through this API. */
  inputText?: string;
  /** Hard wall-clock limit; the container is forcibly stopped if exceeded. */
  timeoutMs?: number;
}

export interface SandboxExecutionResult {
  stdout: string;
  stderr: string;
  exitCode: number;
  timedOut: boolean;
}

const DEFAULT_TIMEOUT_MS = 10_000;
const CONTAINER_SCRIPT_PATH = "/skill/script.js";
/** The fixed path a script reads its `inputText` from, if any. Exported so skill scripts and this
 * package's own tests agree on the contract without duplicating the literal string. */
export const SANDBOX_INPUT_PATH = "/scratch/input.txt";

/**
 * testcontainers@12.1.0's `withResourcesQuota({ memory, cpu })` measures `memory` in GiB
 * (internally: `Math.ceil(memory * 1024 ** 3)` bytes — see
 * generic-container.js's `withResourcesQuota`) and `cpu` in whole CPU cores (internally:
 * `Math.ceil(cpu * 10 ** 9)` NanoCpus). 0.25 GiB = 256 MiB, which is the actual memory ceiling we
 * want per sandboxed script run.
 */
const MEMORY_QUOTA_GIB = 0.25;
const CPU_QUOTA_CORES = 0.5;

/** A simple in-process counting semaphore bounding how many sandbox containers run concurrently
 * — mirrors apps/worker's WORKER_GLOBAL_CONCURRENCY role, applied here to prevent unbounded
 * container sprawl under load. No new dependency: a counter plus a FIFO queue of waiters. */
class Semaphore {
  private available: number;
  private readonly waiters: (() => void)[] = [];

  constructor(concurrency: number) {
    this.available = concurrency;
  }

  async acquire(): Promise<() => void> {
    if (this.available > 0) {
      this.available -= 1;
      return () => this.release();
    }
    await new Promise<void>((resolve) => this.waiters.push(resolve));
    this.available -= 1;
    return () => this.release();
  }

  private release(): void {
    this.available += 1;
    const next = this.waiters.shift();
    if (next) next();
  }
}

const DEFAULT_MAX_CONCURRENT_SANDBOXES = 4;
const globalSemaphore = new Semaphore(
  Number(process.env.SANDBOX_MAX_CONCURRENCY) > 0
    ? Number(process.env.SANDBOX_MAX_CONCURRENCY)
    : DEFAULT_MAX_CONCURRENT_SANDBOXES,
);

export async function runSandboxedScript(request: SandboxExecutionRequest): Promise<SandboxExecutionResult> {
  const release = await globalSemaphore.acquire();
  try {
    const container = new GenericContainer("node:22-alpine")
      .withNetworkMode("none")
      .withUser("node")
      .withResourcesQuota({ memory: MEMORY_QUOTA_GIB, cpu: CPU_QUOTA_CORES })
      .withUlimits({ nproc: { soft: 64, hard: 64 } })
      .withBindMounts([{ source: request.scriptHostPath, target: CONTAINER_SCRIPT_PATH, mode: "ro" }])
      .withTmpFs({ "/scratch": "rw,size=16m" })
      // Idle keep-alive command: the actual script run happens via .exec() below, once the
      // container (and its /scratch tmpfs) is up and we've had a chance to write the input file.
      .withCommand(["tail", "-f", "/dev/null"]);

    const started = await container.start();
    try {
      if (request.inputText !== undefined) {
        // NOTE: we deliberately do NOT use `copyContentToContainer` (docker cp) here. Verified
        // against this host's Docker engine that copying into a path mounted via `withTmpFs`
        // silently no-ops: the call resolves without error, but the file never appears inside the
        // container (confirmed both through testcontainers and with the raw `docker cp` CLI
        // against a plain `docker run --tmpfs` container — this is a Docker engine limitation, not
        // a testcontainers bug: `docker cp` writes through the container's graph-driver storage
        // path on the host side, which a live kernel tmpfs mount is not part of). Instead we write
        // the input from *inside* the container's own mount namespace via `exec`, passing the text
        // through an exec-scoped environment variable (never interpolated into the shell command
        // string itself, so arbitrary content — including quotes/newlines — is safe).
        const writeInputResult = await started.exec(
          ["sh", "-c", `printf '%s' "$SANDBOX_INPUT_TEXT" > ${SANDBOX_INPUT_PATH}`],
          { env: { SANDBOX_INPUT_TEXT: request.inputText } },
        );
        if (writeInputResult.exitCode !== 0) {
          throw new Error(`Failed to write sandbox input file: ${writeInputResult.stderr}`);
        }
      }

      const execPromise = started.exec(["node", CONTAINER_SCRIPT_PATH, ...request.args]);
      const timeoutMs = request.timeoutMs ?? DEFAULT_TIMEOUT_MS;
      const timeout = new Promise<"timeout">((resolve) => setTimeout(() => resolve("timeout"), timeoutMs));

      const raced = await Promise.race([execPromise, timeout]);
      if (raced === "timeout") {
        return { stdout: "", stderr: "", exitCode: -1, timedOut: true };
      }
      return { stdout: raced.stdout, stderr: raced.stderr, exitCode: raced.exitCode, timedOut: false };
    } finally {
      await started.stop({ timeout: 1_000 });
    }
  } finally {
    release();
  }
}
