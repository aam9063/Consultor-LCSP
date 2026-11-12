import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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

const feedbackCreated = {
  id: 1,
  voto: 1,
  actualizado: false,
  creada_en: "2026-11-12T10:00:00Z",
  actualizada_en: "2026-11-12T10:00:00Z",
};

interface SentFeedbackBody {
  pregunta: string;
  respuesta: string;
  citas: { articulo: string; apartado: string | null }[];
  modelo: string;
  voto: number;
  comentario: string | null;
}

function sentFeedbackBody(call: { init: RequestInit | undefined }): SentFeedbackBody {
  const rawBody = call.init?.body;
  if (typeof rawBody !== "string") {
    throw new Error("POST /feedback was sent without a JSON string body");
  }
  return JSON.parse(rawBody) as SentFeedbackBody;
}

function feedbackCallsOf(fetchMock: ReturnType<typeof installFetchStub>): {
  input: RequestInfo | URL;
  init: RequestInit | undefined;
}[] {
  return fetchMock.mock.calls
    .filter(([input]) => {
      const url =
        typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      return url.endsWith("/feedback");
    })
    .map(([input, init]) => ({ input, init }));
}

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

describe("ConsultaView feedback (S8)", () => {
  it("posts the exact payload, shows the pressed state, and switching the vote updates it", async () => {
    const fetchMock = installFetchStub((url, method) => {
      if (url.endsWith("/consultas")) return { body: consultaResponse };
      if (url.endsWith("/feedback") && method === "POST") {
        return { status: 201, body: feedbackCreated };
      }
      return undefined;
    });

    renderConsulta();
    await askQuestion();

    const up = screen.getByRole("button", { name: "Me ha servido" });
    const down = screen.getByRole("button", { name: "No me ha servido" });
    expect(up).toHaveAttribute("aria-pressed", "false");
    expect(down).toHaveAttribute("aria-pressed", "false");

    await userEvent.click(up);

    const calls = feedbackCallsOf(fetchMock);
    expect(calls).toHaveLength(1);
    const call = calls[0];
    if (call === undefined) {
      throw new Error("POST /feedback was not sent");
    }
    expect(call.init?.method).toBe("POST");
    expect(sentFeedbackBody(call)).toEqual({
      pregunta: "¿Qué garantía definitiva debo depositar?",
      respuesta: consultaResponse.respuesta,
      citas: [
        { articulo: "107", apartado: null },
        { articulo: "108", apartado: null },
      ],
      modelo: "deepseek-v4-flash",
      voto: 1,
      comentario: null,
    });

    expect(up).toHaveAttribute("aria-pressed", "true");
    expect(down).toHaveAttribute("aria-pressed", "false");
    expect(
      await screen.findByText(
        /tu valoración se guarda en esta instalación para mejorar el sistema/i,
      ),
    ).toBeInTheDocument();

    await userEvent.click(down);

    await waitFor(() => {
      expect(feedbackCallsOf(fetchMock)).toHaveLength(2);
    });
    const second = feedbackCallsOf(fetchMock)[1];
    if (second === undefined) {
      throw new Error("second POST /feedback was not sent");
    }
    expect(sentFeedbackBody(second).voto).toBe(-1);
    expect(down).toHaveAttribute("aria-pressed", "true");
    expect(up).toHaveAttribute("aria-pressed", "false");
  });

  it("keeps the answer visible and shows a non-blocking error when the vote fails", async () => {
    installFetchStub((url, method) => {
      if (url.endsWith("/consultas")) return { body: consultaResponse };
      if (url.endsWith("/feedback") && method === "POST") {
        return {
          status: 500,
          body: { error: { code: "db_error", message: "No se pudo guardar." } },
        };
      }
      return undefined;
    });

    renderConsulta();
    await askQuestion();

    const answer = await screen.findByText(
      /la garantía definitiva es el 5 % del precio/i,
    );

    await userEvent.click(screen.getByRole("button", { name: "Me ha servido" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /no se pudo guardar tu valoración/i,
    );
    expect(answer).toBeVisible();
    expect(screen.getByRole("heading", { name: "Respuesta" })).toBeInTheDocument();
  });
});

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

  it("clears the article panel when the shown consulta changes (R3-002)", async () => {
    installFetchStub((url) => {
      if (url.endsWith("/articulos/107")) return { body: article107 };
      if (url.endsWith("/articulos/108")) return { body: article108 };
      return undefined;
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const otherConsulta = {
      ...consultaResponse,
      pregunta: "¿Cómo se constituye la garantía?",
      citas: [{ articulo: "108", apartado: null }],
      chunks: [chunk108],
    };
    const view = (consulta: typeof consultaResponse) => (
      <QueryClientProvider client={queryClient}>
        <ConsultaView
          history={[]}
          activeConsulta={consulta}
          onSelectHistory={vi.fn()}
          onConsultaCompleted={vi.fn()}
        />
      </QueryClientProvider>
    );

    const { rerender } = render(view(consultaResponse));
    await userEvent.click(screen.getByRole("button", { name: "Ver art. 107" }));
    expect(
      await screen.findByRole("complementary", { name: "Texto del artículo" }),
    ).toHaveTextContent(/texto consolidado del artículo 107/i);

    rerender(view(otherConsulta));

    const panel = screen.getByRole("complementary", { name: "Texto del artículo" });
    expect(panel).not.toHaveTextContent(/texto consolidado del artículo 107/i);
    expect(panel).toHaveTextContent(/pulsa una cita/i);
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
