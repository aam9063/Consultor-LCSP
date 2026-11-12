import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { RevisorView } from "../../src/features/revisor/RevisorView";
import { installFetchStub } from "./helpers";

const article193 = {
  articulo: "193",
  chunks: [
    {
      id: 9,
      articulo: "193",
      apartado: null,
      titulo: "Penalidades por demora",
      url: "https://www.boe.es/buscar/act.php?id=BOE-A-2017-12902#a1-100",
      texto: "Texto del artículo 193 sobre penalidades por demora.",
    },
  ],
};

const revisionResponse = {
  clausula:
    "Cláusula 29. Penalidades. En caso de demora, penalidad diaria de 2,00 euros por cada 1.000 euros del precio.",
  avisos: [
    {
      tipo: "posible_incumplimiento",
      explicacion:
        "La cuantía diaria parece superior a la general prevista para la demora.",
      articulos_citados: [{ articulo: "193", apartado: null }],
      cita_de_la_clausula: "…una penalidad diaria de 2,00 euros por cada 1.000 euros…",
    },
  ],
  avisos_invalidos: [],
  sin_observaciones: false,
  observaciones: null,
  modelo: "deepseek-v4-flash",
  chunks: [],
};

function renderRevisor() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <RevisorView />
    </QueryClientProvider>,
  );
}

async function reviewClause() {
  await userEvent.type(
    screen.getByLabelText("Texto de la cláusula"),
    "Cláusula 29. Penalidades. En caso de demora, penalidad diaria de 2,00 euros por cada 1.000 euros del precio.",
  );
  await userEvent.click(screen.getByRole("button", { name: "Revisar cláusula" }));
}

describe("RevisorView (AC-08, S5)", () => {
  it("renders a warning card with its cited article and opens the article panel", async () => {
    installFetchStub((url) => {
      if (url.endsWith("/revisiones")) return { body: revisionResponse };
      if (url.endsWith("/articulos/193")) return { body: article193 };
      return undefined;
    });

    renderRevisor();
    await reviewClause();

    const avisos = await screen.findByRole("region", { name: "Avisos" });
    expect(within(avisos).getByText("! Posible incumplimiento")).toBeInTheDocument();
    expect(
      within(avisos).getByText(/la cuantía diaria parece superior/i),
    ).toBeInTheDocument();
    expect(
      within(avisos).getByText(/penalidad diaria de 2,00 euros/i),
    ).toBeInTheDocument();

    await userEvent.click(within(avisos).getByRole("button", { name: "Ver art. 193" }));

    const panel = await screen.findByRole("complementary", {
      name: "Texto del artículo",
    });
    expect(panel).toHaveTextContent(/texto del artículo 193/i);
  });

  it("renders the sin observaciones fundadas state when the clause has no warnings", async () => {
    installFetchStub((url) => {
      if (url.endsWith("/revisiones")) {
        return {
          body: {
            ...revisionResponse,
            avisos: [],
            sin_observaciones: true,
            observaciones: "sin observaciones fundadas",
          },
        };
      }
      return undefined;
    });

    renderRevisor();
    await reviewClause();

    expect(await screen.findByText(/sin observaciones fundadas/i)).toBeInTheDocument();
  });

  it("lists discarded avisos as an explicit secondary list", async () => {
    installFetchStub((url) => {
      if (url.endsWith("/revisiones")) {
        return {
          body: {
            ...revisionResponse,
            avisos_invalidos: [
              {
                tipo: "posible_incumplimiento",
                explicacion: null,
                cita_de_la_clausula: "…cláusula con cita inválida…",
                articulos_citados: ["[art. 999]"],
                motivos: ["articulo_no_recuperado"],
              },
            ],
          },
        };
      }
      return undefined;
    });

    renderRevisor();
    await reviewClause();

    const descartados = await screen.findByRole("region", { name: "Avisos descartados" });
    expect(
      within(descartados).getByText(/cláusula con cita inválida/i),
    ).toBeInTheDocument();
    expect(within(descartados).getByText(/articulo_no_recuperado/)).toBeInTheDocument();
  });
});
