import "server-only";

const base = process.env.LOYMEM_API_URL ?? "http://localhost:8000";

export async function serverGet<T>(path: string): Promise<T | null> {
  const res = await fetch(`${base}/api/v1${path}`, { cache: "no-store" });
  if (!res.ok) return null;
  return (await res.json()) as T;
}
