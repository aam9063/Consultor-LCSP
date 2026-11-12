import { afterEach, vi, type Mock } from "vitest";

export interface StubResponse {
  status?: number;
  body: unknown;
}

export type FetchHandler = (url: string, method: string) => StubResponse | undefined;

export type FetchMock = Mock<(input: RequestInfo | URL, init?: RequestInit) => Response>;

export function installFetchStub(handler: FetchHandler): FetchMock {
  const fetchMock: FetchMock = vi.fn(
    (input: RequestInfo | URL, init?: RequestInit): Response => {
      const url =
        typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const method = init?.method ?? "GET";
      const result = handler(url, method);
      if (result === undefined) {
        throw new Error(`Unexpected fetch call: ${method} ${url}`);
      }
      return new Response(JSON.stringify(result.body), {
        status: result.status ?? 200,
        headers: { "Content-Type": "application/json" },
      });
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});
