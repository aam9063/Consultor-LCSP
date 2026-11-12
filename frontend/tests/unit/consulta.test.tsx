import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConsultaView } from "../../src/features/consulta/ConsultaView";
import { installFetchStub } from "./helpers";

const article107 = {
  articulo: "107",
  chunks: [
    {
      id: 11,
      articulo: "107",
      apartado: null,
      titulo: "Exigencia y cuantía de la garantía definitiva",
      url: "https://www.boe.es/buscar/act.php?id=BOE-A-2017-12902#a1-19",
      texto:
        "Texto consolidado del artículo 107: la garantía definitiva es el 5 % del precio de licitación.",
    },
  ],
};

const article108 = {
  articulo: "108",
  chunks: [
    {
      id: 12,
      articulo: "108",
      apartado: null,
      titulo: "Forma de prestación de la garantía definitiva",
      url: "https://www.boe.es/buscar/act.php?id=BOE-A-2017-12902#a1-20",
      texto:
        "Texto consolidado del artículo 108: en efectivo, mediante aval o con seguro de caución.",
    },
  ],
};

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

const chunk108 = {
  id: 12,
  articulo: "108",
  apartado: null,
  titulo: "Forma de prestación de la garantía definitiva",
  url: "https://www.boe.es/buscar/act.php?id=BOE-A-2017-12902#a1-20",
  texto: "Texto del artículo 108.",
  score: 0.81,
  branches: ["vector"],
};

const consultaResponse = {
  pregunta: "¿Qué garantía definitiva debo depositar?",
  respuesta:
    "La garantía definitiva es el 5 % del precio de licitación, IVA excluido. [art. 107] Puede constituirse en efectivo, mediante aval o con un seguro de caución. [art. 108]",
  citas: [
    { articulo: "107", apartado: null },
    { articulo: "108", apartado: null },
  ],
  abstencion: false,
  motivo_abstencion: null,
  advertencia: null,
  afirmaciones_no_respaldadas: [],
  modelo: "deepseek-v4-flash",
  chunks: [chunk107, chunk108],
};

function renderConsulta(onConsultaCompleted = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ConsultaView
        history={[]}
        activeConsulta={null}
        onSelectHistory={vi.fn()}
        onConsultaCompleted={onConsultaCompleted}
      />
    </QueryClientProvider>,
  );
}

async function askQuestion() {
  await userEvent.type(
    screen.getByLabelText("Tu pregunta sobre la LCSP"),
    "¿Qué garantía definitiva debo depositar?",
  );
  await userEvent.click(screen.getByRole("button", { name: "Consultar" }));
}

describe("ConsultaView (AC-09)", () => {
  it("shows the cited article text in the side panel when a chip is clicked", async () => {
    installFetchStub((url) => {
      if (url.endsWith("/consultas")) return { body: consultaResponse };
      if (url.endsWith("/articulos/107")) return { body: article107 };
      if (url.endsWith("/articulos/108")) return { body: article108 };
      return undefined;
    });

    renderConsulta();
    await askQuestion();

    expect(
      await screen.findByText(/la garantía definitiva es el 5 % del precio/i),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Ver art. 107" }));

    const panel = await screen.findByRole("complementary", {
      name: "Texto del artículo",
    });
    expect(panel).toHaveTextContent(/texto consolidado del artículo 107/i);

    await userEvent.click(screen.getByRole("button", { name: "Ver art. 108" }));
    expect(
      screen.getByRole("complementary", { name: "Texto del artículo" }),
    ).toHaveTextContent(/texto consolidado del artículo 108/i);
  });

  it("renders the abstention state with its reason instead of an answer", async () => {
    installFetchStub((url) => {
      if (url.endsWith("/consultas")) {
        return {
          body: {
            ...consultaResponse,
            respuesta: "No encuentro base en la LCSP para responder esto.",
            citas: [],
            abstencion: true,
            motivo_abstencion:
              "La mejor puntuación del reranker está por debajo del umbral.",
            chunks: [],
          },
        };
      }
      return undefined;
    });

    renderConsulta();
    await askQuestion();

    expect(await screen.findByText(/no encuentro base en la lcsp/i)).toBeInTheDocument();
    expect(screen.getByText(/por debajo del umbral/i)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Respuesta" })).not.toBeInTheDocument();
  });

  it("renders the unsupported-claims warning when the answer has unbacked claims", async () => {
    installFetchStub((url) => {
      if (url.endsWith("/consultas")) {
        return {
          body: {
            ...consultaResponse,
            respuesta:
              "La garantía definitiva es el 5 % del precio de licitación. [art. 107]",
            citas: [{ articulo: "107", apartado: null }],
            chunks: [chunk107],
            advertencia:
              "Algunas afirmaciones no están respaldadas por los artículos recuperados.",
            afirmaciones_no_respaldadas: ["El plazo máximo de pago es de sesenta días."],
          },
        };
      }
      return undefined;
    });

    renderConsulta();
    await askQuestion();

    expect(
      await screen.findByText(/no están respaldadas por los artículos recuperados/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText("El plazo máximo de pago es de sesenta días."),
    ).toBeInTheDocument();
  });
});
