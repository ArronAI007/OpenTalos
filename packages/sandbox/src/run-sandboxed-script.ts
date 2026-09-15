import { extname } from "node:path";
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
const CONTAINER_SCRIPT_DIR = "/skill";

/**
 * Maps a script's file extension to how it's invoked inside the container. This allowlist is
 * itself part of the sandbox's security boundary — an unrecognized extension is rejected up front
 * (see resolveRuntime below) rather than attempting to sniff a shebang line and execute
 * accordingly; only these exact, known-safe invocation shapes are ever used.
 */
const RUNTIME_COMMAND_BY_EXTENSION: Record<string, (containerPath: string, args: string[]) => string[]> = {
  ".js": (containerPath, args) => ["node", containerPath, ...args],
  ".mjs": (containerPath, args) => ["node", containerPath, ...args],
  ".cjs": (containerPath, args) => ["node", containerPath, ...args],
  ".py": (containerPath, args) => ["python3", containerPath, ...args],
};

interface ResolvedRuntime {
  /** Absolute in-container path the script is bind-mounted at, preserving its real extension. */
  containerPath: string;
  /** The full command to exec inside the container to run the script. */
  command: string[];
}

/** Throws a clear error for any extension not in RUNTIME_COMMAND_BY_EXTENSION. Called before the
 * concurrency semaphore is acquired or any container is started, so an unsupported script type
 * fails fast without touching Docker at all. */
function resolveRuntime(scriptHostPath: string, args: string[]): ResolvedRuntime {
  const ext = extname(scriptHostPath);
  const buildCommand = RUNTIME_COMMAND_BY_EXTENSION[ext];
  if (!buildCommand) {
    throw new Error(
      `Unsupported script type "${ext || "(no extension)"}" for "${scriptHostPath}". ` +
        `Supported extensions: ${Object.keys(RUNTIME_COMMAND_BY_EXTENSION).join(", ")}.`,
    );
  }
  const containerPath = `${CONTAINER_SCRIPT_DIR}/script${ext}`;
  return { containerPath, command: buildCommand(containerPath, args) };
}

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

/**
 * Maximum size, in bytes, allowed for `inputText`. `inputText` is written into the container by
 * passing it as the value of a *single* exec-scoped environment variable (`SANDBOX_INPUT_TEXT`,
 * see the `started.exec(["sh", "-c", ...], { env: { SANDBOX_INPUT_TEXT: ... } })` call below).
 *
 * The naive assumption is that the relevant ceiling is the total `ARG_MAX` for the whole
 * argv+envp block passed to `execve()` (commonly ~2MB on Linux, higher on macOS). That is NOT
 * what actually bites here: this was empirically verified against this project's real sandbox
 * (testcontainers + Docker, `node:22-alpine`) by bisecting `inputText` sizes directly against
 * `started.exec(...)`, and a *single* environment variable string starts failing with
 * `exec /bin/sh: argument list too long` once it crosses 128 KiB (131,072 bytes) — reproducible
 * consistently between 125,000 bytes (succeeds) and 131,072 bytes (fails). That matches Linux's
 * `MAX_ARG_STRLEN` (32 pages, i.e. 32 × 4096 = 131,072 bytes): the kernel caps the length of any
 * *individual* argv/envp string well below the much larger total `ARG_MAX`, and one big
 * `SANDBOX_INPUT_TEXT` value hits that per-string cap directly, regardless of how much of the
 * total budget is otherwise free.
 *
 * 64 KiB (65,536 bytes) is chosen as a conservative limit: roughly half of the empirically
 * confirmed 128 KiB per-string ceiling (2x safety margin, covering variance across kernels/distros
 * without needing to shave right up to the edge), while still comfortably covering realistic
 * inputs for this feature's actual use case — e.g. the `text-to-table` demo skill reformatting a
 * user-pasted block of delimited text. It deliberately does NOT attempt to support arbitrarily
 * large input (e.g. a multi-megabyte, 100k-row CSV paste): doing that losslessly would require a
 * different transport mechanism entirely (chunking, a mounted file, etc.), which is out of scope
 * here. The goal of this limit is only to fail fast with a clear, actionable error instead of
 * letting an oversized value hit the OS-level per-argument wall and surface as a confusing
 * `exec /bin/sh: argument list too long`-style failure.
 */
export const MAX_INPUT_TEXT_BYTES = 65_536;

export async function runSandboxedScript(request: SandboxExecutionRequest): Promise<SandboxExecutionResult> {
  if (request.inputText !== undefined) {
    const inputByteLength = Buffer.byteLength(request.inputText, "utf8");
    if (inputByteLength > MAX_INPUT_TEXT_BYTES) {
      throw new Error(
        `Sandbox input text is too large: ${inputByteLength} bytes exceeds the ${MAX_INPUT_TEXT_BYTES}-byte limit. ` +
          `Provide a smaller input — this sandbox transport cannot support arbitrarily large payloads.`,
      );
    }
  }

  // Resolved before acquiring the concurrency semaphore or starting any container, so an
  // unsupported script extension fails fast without touching Docker at all.
  const runtime = resolveRuntime(request.scriptHostPath, request.args);

  const release = await globalSemaphore.acquire();
  try {
    const container = new GenericContainer("nikolaik/python-nodejs:python3.12-nodejs22")
      .withNetworkMode("none")
      // "pn" (uid 1000) is this image's only unprivileged user — verified via
      // `docker run --rm --user pn nikolaik/python-nodejs:python3.12-nodejs22 id`. The plain
      // `node:22-alpine` image used a "node" user; this image has no such user.
      .withUser("pn")
      .withResourcesQuota({ memory: MEMORY_QUOTA_GIB, cpu: CPU_QUOTA_CORES })
      .withUlimits({ nproc: { soft: 64, hard: 64 } })
      .withBindMounts([{ source: request.scriptHostPath, target: runtime.containerPath, mode: "ro" }])
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

      const execPromise = started.exec(runtime.command);
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
