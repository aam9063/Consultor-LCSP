import { useMutation } from "@tanstack/react-query";
import { useState, type SyntheticEvent } from "react";

import { ArticlePanel } from "../../components/ArticlePanel";
import { ApiError, postRevision, type RevisionResponse } from "../../lib/api";
import { citationLabel } from "../../lib/answerText";

interface TipoStyle {
  label: string;
  className: string;
}

const TIPO_STYLES: Record<string, TipoStyle> = {
  posible_incumplimiento: {
    label: "! Posible incumplimiento",
    className: "bg-decision-nogo-bg text-decision-nogo",
  },
  ambiguedad: {
    label: "? Ambigüedad",
    className: "bg-decision-review-bg text-decision-review",
  },
  ok: {
    label: "✓ OK",
    className: "bg-decision-go-bg text-decision-go",
  },
};

function tipoStyle(tipo: string): TipoStyle {
  const known = TIPO_STYLES[tipo];
  return known ?? { label: tipo, className: "border-subtle text-ink-soft bg-canvas" };
}

const SECTION_CARD =
  "border-subtle bg-surface flex flex-col gap-2.5 rounded-xl border p-4";

export function RevisorView() {
  const [clausula, setClausula] = useState("");
  const [selectedArticulo, setSelectedArticulo] = useState<string | null>(null);

  const revision = useMutation({
    mutationFn: postRevision,
  });

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = clausula.trim();
    if (trimmed.length === 0) {
      return;
    }
    revision.mutate(trimmed);
  }

  const result: RevisionResponse | undefined = revision.data;

  const incumplimientos =
    result?.avisos.filter((a) => a.tipo === "posible_incumplimiento").length ?? 0;
  const ambiguedades = result?.avisos.filter((a) => a.tipo === "ambiguedad").length ?? 0;

  return (
    <main className="mx-auto flex max-w-[1360px] flex-col gap-5 px-6 py-6">
      <div className="flex flex-col gap-1.5">
        <h1 className="font-display text-3xl font-bold">Revisor de cláusulas</h1>
        <p className="text-ink-muted">
          Pega una cláusula de un pliego. Te señalo posibles choques con la LCSP, cada uno
          con su artículo.
        </p>
      </div>

      <div className="flex flex-wrap items-start gap-5">
        <section
          aria-label="Cláusula"
          className={`${SECTION_CARD} min-w-0 flex-1 basis-[460px]`}
        >
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <label htmlFor="clausula" className="font-semibold">
              Texto de la cláusula
            </label>
            <textarea
              id="clausula"
              rows={14}
              value={clausula}
              onChange={(event) => {
                setClausula(event.target.value);
              }}
              className="border-border-input focus:border-lcsp focus:ring-lcsp w-full resize-vertical rounded-lg border p-3.5 leading-relaxed font-[inherit] focus:outline focus:outline-2"
            />
            <div className="flex flex-wrap items-center gap-2.5">
              <span className="text-ink-muted text-[13px]">Hasta unas 800 palabras</span>
              <button
                type="submit"
                disabled={revision.isPending || clausula.trim().length === 0}
                className="bg-lcsp hover:bg-lcsp-deep focus-visible:ring-lcsp ml-auto min-h-[44px] rounded-[10px] px-4.5 font-semibold text-white focus-visible:ring-2"
              >
                {revision.isPending ? "Revisando…" : "Revisar cláusula"}
              </button>
            </div>
            {revision.isError && (
              <p className="text-decision-nogo text-sm" role="alert">
                No se pudo revisar la cláusula:{" "}
                {revision.error instanceof ApiError
                  ? revision.error.message
                  : "error inesperado."}
              </p>
            )}
          </form>
        </section>

        <section
          aria-label="Avisos"
          className="flex min-w-0 flex-1 basis-[520px] flex-col gap-3"
        >
          {result !== undefined && result.sin_observaciones && (
            <div className="border-subtle bg-surface rounded-xl border p-5">
              <p className="font-semibold">
                {result.observaciones ?? "sin observaciones fundadas"}
              </p>
              <p className="text-ink-muted mt-1.5 text-sm">
                No hay avisos que mostrar para esta cláusula.
              </p>
            </div>
          )}

          {result !== undefined &&
            !result.sin_observaciones &&
            result.avisos.length > 0 && (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="font-display text-xl font-semibold">
                    {result.avisos.length}{" "}
                    {result.avisos.length === 1 ? "aviso" : "avisos"}
                  </h2>
                  {incumplimientos > 0 && (
                    <span className="bg-decision-nogo-bg text-decision-nogo rounded-full px-2.5 py-1 text-[13px] font-semibold">
                      {incumplimientos}{" "}
                      {incumplimientos === 1
                        ? "posible incumplimiento"
                        : "posibles incumplimientos"}
                    </span>
                  )}
                  {ambiguedades > 0 && (
                    <span className="bg-decision-review-bg text-decision-review rounded-full px-2.5 py-1 text-[13px] font-semibold">
                      {ambiguedades} {ambiguedades === 1 ? "ambigüedad" : "ambigüedades"}
                    </span>
                  )}
                </div>
                {result.avisos.map((aviso, index) => (
                  <article
                    key={index}
                    className="border-subtle bg-surface flex flex-col gap-2.5 rounded-xl border p-4"
                  >
                    <div className="flex flex-wrap items-center gap-2.5">
                      <span
                        className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[13px] font-bold ${tipoStyle(aviso.tipo).className}`}
                      >
                        {tipoStyle(aviso.tipo).label}
                      </span>
                      {aviso.articulos_citados.map((citation, citationIndex) => (
                        <button
                          key={citationIndex}
                          type="button"
                          onClick={() => {
                            setSelectedArticulo(citation.articulo);
                          }}
                          aria-label={`Ver ${citationLabel(citation)}`}
                          className={`bg-nav-active text-lcsp border-nav-active-border inline-flex min-h-[30px] items-center rounded-full border px-2.5 text-[13px] font-semibold ${
                            selectedArticulo === citation.articulo
                              ? "ring-lcsp ring-2"
                              : ""
                          }`}
                        >
                          {citationLabel(citation)}
                        </button>
                      ))}
                    </div>
                    <blockquote className="bg-panel-quote text-ink-soft m-0 rounded-md px-3 py-2 text-sm italic">
                      {aviso.cita_de_la_clausula}
                    </blockquote>
                    <p className="m-0 leading-relaxed">{aviso.explicacion}</p>
                  </article>
                ))}
              </>
            )}

          {result !== undefined && result.avisos_invalidos.length > 0 && (
            <div
              role="region"
              aria-label="Avisos descartados"
              className="border-subtle rounded-xl border border-dashed p-4"
            >
              <h3 className="text-ink-muted text-[13px] font-semibold tracking-[0.04em] uppercase">
                Avisos descartados (no superaron la validación)
              </h3>
              <ul className="m-0 mt-2 flex list-disc flex-col gap-1.5 pl-5 text-sm">
                {result.avisos_invalidos.map((invalido, index) => (
                  <li key={index} className="text-ink-muted">
                    {invalido.cita_de_la_clausula !== null && (
                      <span className="text-ink-soft italic">
                        "{invalido.cita_de_la_clausula}"{" "}
                      </span>
                    )}
                    <span>— motivos: {invalido.motivos.join(", ")}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {selectedArticulo !== null && <ArticlePanel numero={selectedArticulo} />}
        </section>
      </div>
    </main>
  );
}
