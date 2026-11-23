export class ApiError extends Error {
  constructor(
    public code: string,
    public status: number,
  ) {
    super(code);
  }
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}`, {
      credentials: "same-origin",
      ...rest,
      headers: {
        "X-Loymem": "1",
        ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch {
    throw new ApiError("network", 0);
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "generic";
    throw new ApiError(detail, res.status);
  }
  return body as T;
}

export type Palette = { background: string; text: string };

export type CardData = {
  business: { name: string; slug: string; booking_url: string | null; palette: Palette };
  first_name: string | null;
  program: { name: string; stamps_required: number; reward: string };
  stamps: number;
  rewards: { id: string; description: string }[];
  scan_token: string;
  marketing: boolean;
};
