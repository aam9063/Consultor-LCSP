import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { App } from "../../src/app/App";
import { installFetchStub } from "./helpers";

const chunk107 = {
  id: 11,
  articulo: "107",
  apartado: null,
  titulo: "Exigencia y cuantía de la garantía definitiva",
  url: "https://www.boe.es/buscar/act.php?id=BOE-A-2017-12902#a1-19",
  texto: "Texto del artículo 107.",
  score: 0.94,
  branches: ["direct"],
};

function consultaResponse(pregunta: string, respuesta: string) {
  return {
    pregunta,
    respuesta,
    citas: [{ articulo: "107", apartado: null }],
    abstencion: false,
    motivo_abstencion: null,
    advertencia: null,
    afirmaciones_no_respaldadas: [],
    modelo: "deepseek-v4-flash",
    chunks: [chunk107],
  };
}

describe("Session history (S5)", () => {
  it("lists the queries of the session and reopens a previous answer", async () => {
    const consultas = [
      consultaResponse("primera", "Respuesta de la primera consulta. [art. 107]"),
      consultaResponse("segunda", "Respuesta de la segunda consulta. [art. 107]"),
    ];
    let call = 0;
    installFetchStub((url) => {
      if (url.endsWith("/health")) return { body: { status: "ok" } };
      if (url.endsWith("/consultas")) {
        const response = consultas[call];
        call += 1;
        return response === undefined
          ? { status: 500, body: { error: { code: "stub", message: "no more stubs" } } }
          : { body: response };
      }
      return undefined;
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await userEvent.type(screen.getByLabelText("Tu pregunta sobre la LCSP"), "primera");
    await userEvent.click(screen.getByRole("button", { name: "Consultar" }));
    expect(
      await screen.findByText(/respuesta de la primera consulta/i),
    ).toBeInTheDocument();

    await userEvent.clear(screen.getByLabelText("Tu pregunta sobre la LCSP"));
    await userEvent.type(screen.getByLabelText("Tu pregunta sobre la LCSP"), "segunda");
    await userEvent.click(screen.getByRole("button", { name: "Consultar" }));
    expect(
      await screen.findByText(/respuesta de la segunda consulta/i),
    ).toBeInTheDocument();

    const historyNav = screen.getByRole("navigation", { name: "Historial de la sesión" });
    const entries = within(historyNav).getAllByRole("button");
    expect(entries).toHaveLength(2);
    expect(within(historyNav).getByText("primera")).toBeInTheDocument();
    expect(within(historyNav).getByText("segunda")).toBeInTheDocument();

    await userEvent.click(within(historyNav).getByRole("button", { name: "primera" }));
    expect(screen.getByText(/respuesta de la primera consulta/i)).toBeInTheDocument();
  });
});
