import { expect, test, type Page } from "@playwright/test";

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
        "Texto consolidado del artículo 107: la garantía definitiva es el 5 % del precio de licitación, IVA excluido.",
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
        "Texto consolidado del artículo 108 sobre la forma de prestación de la garantía.",
    },
  ],
};

const consultaResponse = {
  pregunta: "¿Qué garantía definitiva tengo que depositar si me adjudican una obra?",
  respuesta:
    "Con carácter general, la garantía definitiva es el 5 % del precio final ofertado, IVA excluido. [art. 107] Puede constituirse en efectivo o valores, mediante aval o con un seguro de caución. [art. 108]",
  citas: [
    { articulo: "107", apartado: null },
    { articulo: "108", apartado: null },
  ],
  abstencion: false,
  motivo_abstencion: null,
  advertencia: null,
  afirmaciones_no_respaldadas: [],
  modelo: "deepseek-v4-flash",
  chunks: [
    {
      id: 11,
      articulo: "107",
      apartado: null,
      titulo: "Exigencia y cuantía de la garantía definitiva",
      url: "https://www.boe.es/buscar/act.php?id=BOE-A-2017-12902#a1-19",
      texto: "Texto del artículo 107.",
      score: 0.94,
      branches: ["direct"],
    },
    {
      id: 12,
      articulo: "108",
      apartado: null,
      titulo: "Forma de prestación de la garantía definitiva",
      url: "https://www.boe.es/buscar/act.php?id=BOE-A-2017-12902#a1-20",
      texto: "Texto del artículo 108.",
      score: 0.81,
      branches: ["vector"],
    },
  ],
};

async function stubApi(page: Page): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = (body: unknown, status = 200): Promise<void> =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    if (path.endsWith("/health")) return json({ status: "ok" });
    if (path.endsWith("/consultas")) return json(consultaResponse);
    if (path.endsWith("/articulos/107")) return json(article107);
    if (path.endsWith("/articulos/108")) return json(article108);
    return json({ error: { code: "not_stubbed", message: `No stub for ${path}` } }, 404);
  });
}

test("a citation chip opens the cited article in the side panel", async ({ page }) => {
  await stubApi(page);
  await page.goto("/");

  await page
    .getByLabel("Tu pregunta sobre la LCSP")
    .fill("¿Qué garantía definitiva tengo que depositar si me adjudican una obra?");
  await page.getByRole("button", { name: "Consultar" }).click();

  const panel = page.getByRole("complementary", { name: "Texto del artículo" });
  await expect(panel.getByText(/pulsa una cita/i)).toBeVisible();

  await page.getByRole("button", { name: "Ver art. 107" }).click();
  await expect(panel.getByRole("heading", { name: "Artículo 107" })).toBeVisible();
  await expect(
    panel.getByText(/la garantía definitiva es el 5 % del precio/i),
  ).toBeVisible();

  await page.getByRole("button", { name: "Ver art. 108" }).click();
  await expect(panel.getByRole("heading", { name: "Artículo 108" })).toBeVisible();

  await expect(
    page.getByText("Herramienta de apoyo. No es asesoramiento jurídico"),
  ).toBeVisible();
});
