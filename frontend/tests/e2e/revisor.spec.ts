import { expect, test, type Page } from "@playwright/test";

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
    "Cláusula 29. Penalidades. En caso de demora en el cumplimiento del plazo total, el órgano de contratación impondrá una penalidad diaria de 2,00 euros por cada 1.000 euros del precio del contrato.",
  avisos: [
    {
      tipo: "posible_incumplimiento",
      explicacion:
        "La cuantía diaria parece superior a la general prevista para la demora. Comprueba si el pliego justifica una cuantía distinta.",
      articulos_citados: [{ articulo: "193", apartado: null }],
      cita_de_la_clausula:
        "…una penalidad diaria de 2,00 euros por cada 1.000 euros del precio…",
    },
    {
      tipo: "ambiguedad",
      explicacion:
        "La cláusula no fija el plazo de garantía ni remite a un apartado concreto del pliego.",
      articulos_citados: [{ articulo: "111", apartado: null }],
      cita_de_la_clausula: "…se devolverá una vez finalizado el plazo que se determine.",
    },
  ],
  avisos_invalidos: [],
  sin_observaciones: false,
  observaciones: null,
  modelo: "deepseek-v4-flash",
  chunks: [],
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
    if (path.endsWith("/revisiones")) return json(revisionResponse);
    if (path.endsWith("/articulos/193")) return json(article193);
    if (path.endsWith("/articulos/111")) {
      return json({
        articulo: "111",
        chunks: [
          {
            id: 30,
            articulo: "111",
            apartado: null,
            titulo: "Devolución y cancelación de las garantías definitivas",
            url: "https://www.boe.es/buscar/act.php?id=BOE-A-2017-12902#a1-115",
            texto: "Texto del artículo 111 sobre devolución de garantías definitivas.",
          },
        ],
      });
    }
    return json({ error: { code: "not_stubbed", message: `No stub for ${path}` } }, 404);
  });
}

test("the revisor shows warning cards and opens the cited article", async ({ page }) => {
  await stubApi(page);
  await page.goto("/revisor");

  await page
    .getByLabel("Texto de la cláusula")
    .fill(
      "Cláusula 29. Penalidades. En caso de demora en el cumplimiento del plazo total, el órgano de contratación impondrá una penalidad diaria de 2,00 euros por cada 1.000 euros del precio del contrato.",
    );
  await page.getByRole("button", { name: "Revisar cláusula" }).click();

  const avisos = page.getByRole("region", { name: "Avisos" });
  await expect(avisos.getByRole("heading", { name: "2 avisos" })).toBeVisible();
  await expect(avisos.getByText("! Posible incumplimiento")).toBeVisible();
  await expect(avisos.getByText("? Ambigüedad")).toBeVisible();

  await avisos.getByRole("button", { name: "Ver art. 193" }).click();
  const panel = page.getByRole("complementary", { name: "Texto del artículo" });
  await expect(panel.getByRole("heading", { name: "Artículo 193" })).toBeVisible();
  await expect(panel.getByText(/texto del artículo 193/i)).toBeVisible();
});
