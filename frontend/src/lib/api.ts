export interface HealthStatus {
  status: string;
}

const API_BASE_URL = import.meta.env.VITE_API_URL ?? "/api";

function isHealthStatus(payload: unknown): payload is HealthStatus {
  return (
    typeof payload === "object" &&
    payload !== null &&
    "status" in payload &&
    typeof payload.status === "string"
  );
}

export async function fetchHealth(): Promise<HealthStatus> {
  const response = await fetch(`${API_BASE_URL}/health`);

  if (!response.ok) {
    throw new Error(`Health check failed with status ${String(response.status)}`);
  }

  const payload: unknown = await response.json();

  if (!isHealthStatus(payload)) {
    throw new Error("Health check returned an unexpected payload");
  }

  return payload;
}
