import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { App } from "../../src/app/App";

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("App shell", () => {
  it("shows the product name and the legal disclaimer", () => {
    renderApp();

    expect(screen.getByRole("heading", { name: /consultor lcsp/i })).toBeInTheDocument();
    expect(screen.getByText(/no es asesoramiento jurídico/i)).toBeInTheDocument();
  });

  it("reports that the API is unreachable when the health check fails", async () => {
    renderApp();

    expect(await screen.findByText(/api no disponible/i)).toBeInTheDocument();
  });
});
