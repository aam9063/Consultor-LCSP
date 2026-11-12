import { useMutation } from "@tanstack/react-query";
import { useState, type SyntheticEvent } from "react";

import { ArticlePanel } from "../../components/ArticlePanel";
import { ApiError, postConsulta, type ConsultaResponse } from "../../lib/api";
import { citationLabel, splitAnswer } from "../../lib/answerText";

interface ConsultaViewProps {
  history: ConsultaResponse[];
  activeConsulta: ConsultaResponse | null;
  onSelectHistory: (consulta: ConsultaResponse) => void;
  onConsultaCompleted: (consulta: ConsultaResponse) => void;
}

export function ConsultaView({
  history,
  activeConsulta,
  onSelectHistory,
  onConsultaCompleted,
}: ConsultaViewProps) {
  const [pregunta, setPregunta] = useState("");
  // The selection belongs to one consulta: switching to another answer (new
  // query or a history entry) must not keep the previous article in the panel.
  const [selection, setSelection] = useState<{
    consulta: ConsultaResponse | null;
    articulo: string;
  } | null>(null);

  const consulta = useMutation({
    mutationFn: postConsulta,
    onSuccess: (response) => {
      onConsultaCompleted(response);
    },
  });

  const shownConsulta = activeConsulta ?? consulta.data ?? null;
  const selectedArticulo =
    selection !== null && selection.consulta === shownConsulta
      ? selection.articulo
      : null;

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = pregunta.trim();
    if (trimmed.length === 0) {
      return;
    }
    consulta.mutate(trimmed);
  }

  const citedArticulos = new Set(
    shownConsulta === null ? [] : shownConsulta.citas.map((cita) => cita.articulo),
  );

  return (
    <main className="mx-auto flex max-w-[1360px] flex-wrap items-start gap-5 px-6 py-6">
      <nav
        aria-label="Historial de la sesión"
        className="flex min-w-0 flex-1 basis-56 flex-col gap-1.5"
      >
        <h2 className="text-ink-muted mb-1.5 text-[13px] font-semibold tracking-[0.04em] uppercase">
          Esta sesión
        </h2>
        {history.length === 0 ? (
          <p className="text-ink-muted text-sm">Aún no has hecho ninguna consulta.</p>
        ) : (
          history.map((entry) => {
            const active = entry === activeConsulta;
            return (
              <button
                key={`${entry.pregunta}-${entry.respuesta.slice(0, 32)}`}
                type="button"
                onClick={() => {
                  onSelectHistory(entry);
                }}
                className={`block min-h-[44px] rounded-lg px-3 py-2.5 text-left text-sm leading-snug ${
                  active ? "bg-nav-active text-lcsp font-semibold" : "text-ink-soft"
                }`}
              >
                {entry.pregunta}
              </button>
            );
          })
        )}
      </nav>

      <section
        aria-label="Consulta"
        className="flex min-w-0 flex-[999] basis-[560px] flex-col gap-4"
      >
        <form
          onSubmit={handleSubmit}
          className="border-subtle bg-surface flex flex-col gap-2.5 rounded-xl border p-4"
        >
          <label htmlFor="pregunta" className="font-semibold">
            Tu pregunta sobre la LCSP
          </label>
          <textarea
            id="pregunta"
            rows={2}
            value={pregunta}
            onChange={(event) => {
              setPregunta(event.target.value);
            }}
            className="border-border-input focus:border-lcsp focus:ring-lcsp w-full resize-vertical rounded-lg border px-3.5 py-3 font-[inherit] focus:outline focus:outline-2"
          />
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="text-ink-muted text-[13px]">
              Puedes preguntar por un artículo concreto: "¿qué dice el art. 193?"
            </span>
            <button
              type="submit"
              disabled={consulta.isPending || pregunta.trim().length === 0}
              className="bg-lcsp hover:bg-lcsp-deep focus-visible:ring-lcsp ml-auto min-h-[44px] rounded-[10px] px-4.5 font-semibold text-white focus-visible:ring-2"
            >
              {consulta.isPending ? "Consultando…" : "Consultar"}
            </button>
          </div>
          {consulta.isError && (
            <p className="text-decision-nogo text-sm" role="alert">
              No se pudo consultar:{" "}
              {consulta.error instanceof ApiError
                ? consulta.error.message
                : "error inesperado."}
            </p>
          )}
        </form>

        {shownConsulta !== null && shownConsulta.abstencion && (
          <article
            aria-label="Abstención"
            className="border-notice-border bg-notice-bg text-notice-text flex flex-col gap-2.5 rounded-xl border p-5"
          >
            <h2 className="font-display text-xl font-semibold">Sin base en la LCSP</h2>
            <p>{shownConsulta.respuesta}</p>
            {shownConsulta.motivo_abstencion !== null && (
              <p className="text-sm">Motivo: {shownConsulta.motivo_abstencion}</p>
            )}
          </article>
        )}

        {shownConsulta !== null && !shownConsulta.abstencion && (
          <article
            aria-label="Respuesta"
            className="border-subtle bg-surface flex flex-col gap-3.5 rounded-xl border p-5"
          >
            <div className="flex flex-wrap items-center gap-2.5">
              <h2 className="font-display text-xl font-semibold">Respuesta</h2>
              <span className="bg-decision-go-bg text-decision-go inline-flex items-center rounded-full px-2.5 py-1 text-[13px] font-semibold">
                ✓ {shownConsulta.citas.length} citas validadas
              </span>
              <span className="text-ink-muted text-[13px]">{shownConsulta.modelo}</span>
            </div>
            <div className="flex flex-col gap-3 leading-relaxed">
              {shownConsulta.respuesta
                .split(/\n{2,}/)
                .map((paragraph, paragraphIndex) => (
                  <p key={paragraphIndex} className="m-0">
                    {splitAnswer(paragraph).map((segment, segmentIndex) =>
                      segment.kind === "text" ? (
                        <span key={segmentIndex}>{segment.text}</span>
                      ) : (
                        <button
                          key={segmentIndex}
                          type="button"
                          onClick={() => {
                            setSelection({
                              consulta: shownConsulta,
                              articulo: segment.articulo,
                            });
                          }}
                          aria-label={`Ver ${segment.label}`}
                          className={`inline-flex min-h-[30px] items-center rounded-full px-2.5 align-middle text-[13px] font-semibold ${
                            selectedArticulo === segment.articulo
                              ? "bg-lcsp border-lcsp border text-white"
                              : "bg-nav-active text-lcsp border-nav-active-border border"
                          }`}
                        >
                          {segment.label}
                        </button>
                      ),
                    )}
                  </p>
                ))}
            </div>
            {shownConsulta.advertencia !== null && (
              <div className="bg-decision-review-bg text-decision-review flex flex-col gap-1.5 rounded-lg border border-transparent p-3.5 text-sm">
                <p className="font-semibold">{shownConsulta.advertencia}</p>
                {shownConsulta.afirmaciones_no_respaldadas.length > 0 && (
                  <ul className="m-0 flex list-disc flex-col gap-1 pl-5">
                    {shownConsulta.afirmaciones_no_respaldadas.map((claim) => (
                      <li key={claim}>{claim}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            <details
              open
              className="border-subtle border-subtle bg-surface rounded-xl border px-4.5 py-3.5"
            >
              <summary className="min-h-[32px] cursor-pointer font-semibold">
                Artículos recuperados (búsqueda híbrida + rerank)
              </summary>
              <div className="mt-2 overflow-x-auto">
                <table className="text-ink w-full min-w-[480px] border-collapse text-left text-sm">
                  <thead>
                    <tr className="text-ink-muted text-[13px]">
                      <th scope="col" className="p-2 font-medium">
                        Artículo
                      </th>
                      <th scope="col" className="p-2 font-medium">
                        Título
                      </th>
                      <th scope="col" className="p-2 font-medium">
                        Rerank
                      </th>
                      <th scope="col" className="p-2 font-medium">
                        Citado
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {shownConsulta.chunks.map((chunk) => (
                      <tr key={chunk.id} className="border-divider border-t">
                        <td className="p-2 font-semibold">{citationLabel(chunk)}</td>
                        <td className="text-ink-soft p-2">{chunk.titulo}</td>
                        <td className="p-2">
                          <div className="flex items-center gap-2">
                            <div className="bg-divider h-1.5 w-20 overflow-hidden rounded-sm">
                              <div
                                className="bg-lcsp h-full"
                                style={{
                                  width: `${Math.round(chunk.score * 100).toString()}%`,
                                }}
                              />
                            </div>
                            <span className="tabular-nums">
                              {chunk.score.toFixed(2).replace(".", ",")}
                            </span>
                          </div>
                        </td>
                        <td className="text-ink-soft p-2">
                          {citedArticulos.has(chunk.articulo) ? "Sí" : "No"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </article>
        )}
      </section>

      {selectedArticulo !== null ? (
        <div className="flex min-w-0 flex-1 basis-[340px] flex-col gap-2">
          <ArticlePanel numero={selectedArticulo} />
        </div>
      ) : (
        <aside
          aria-label="Texto del artículo"
          className="border-subtle bg-surface min-w-0 flex-1 basis-[340px] rounded-xl border p-5"
        >
          <p className="text-ink-muted text-sm">
            Pulsa una cita de la respuesta para ver aquí el texto del artículo, tal como
            se ingirió del BOE.
          </p>
        </aside>
      )}
    </main>
  );
}
