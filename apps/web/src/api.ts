const SESSION_ID = crypto.randomUUID();

function withSession(path: string): string {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}sessionId=${SESSION_ID}`;
}

export async function startRun(message: string): Promise<{ runId: string }> {
  const res = await fetch(withSession("/runs"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) throw new Error(`Failed to start run: ${res.status}`);
  return res.json();
}

export async function resumeRun(runId: string, approved: boolean): Promise<void> {
  const res = await fetch(withSession(`/runs/${runId}/resume`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved }),
  });
  if (!res.ok) throw new Error(`Failed to resume run: ${res.status}`);
}

export async function getRun(runId: string): Promise<{ runId: string; status: string; state: Record<string, unknown> }> {
  const res = await fetch(withSession(`/runs/${runId}`));
  if (!res.ok) throw new Error(`Failed to load run: ${res.status}`);
  return res.json();
}

export function eventsUrl(runId: string): string {
  return withSession(`/runs/${runId}/events`);
}
