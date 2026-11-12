import { useQuery } from "@tanstack/react-query";

import { fetchArticulo } from "../lib/api";

interface ArticlePanelProps {
  numero: string;
}

export function ArticlePanel({ numero }: ArticlePanelProps) {
  const article = useQuery({
    queryKey: ["articulo", numero],
    queryFn: () => fetchArticulo(numero),
    retry: 0,
    staleTime: Number.POSITIVE_INFINITY,
  });

  if (article.isPending) {
    return (
      <aside
        aria-label="Texto del artículo"
        className="border-subtle bg-surface rounded-xl border p-5"
      >
        <p className="text-ink-muted text-sm">Cargando artículo {numero}…</p>
      </aside>
    );
  }

  if (article.isError) {
    return (
      <aside
        aria-label="Texto del artículo"
        className="border-subtle bg-surface rounded-xl border p-5"
      >
        <p className="text-decision-nogo text-sm" role="status">
          No se pudo cargar el artículo {numero}. Comprueba que la API está disponible.
        </p>
      </aside>
    );
  }

  const chunks = article.data.chunks;
  const firstChunk = chunks[0];

  return (
    <aside
      aria-label="Texto del artículo"
      className="border-subtle bg-surface rounded-xl border p-5"
    >
      <div className="flex flex-col gap-3">
        {firstChunk !== undefined && (
          <span className="text-ink-muted text-[13px]">{firstChunk.titulo}</span>
        )}
        <h2 className="font-display text-[22px] font-semibold">Artículo {numero}</h2>
        {chunks.map((chunk) => (
          <div key={chunk.id} className="flex flex-col gap-1.5">
            {chunk.apartado !== null && (
              <p className="text-sm font-semibold">Apartado {chunk.apartado}</p>
            )}
            <div className="bg-panel-tint border-panel-tint-border rounded-lg border p-3.5 text-sm leading-relaxed">
              {chunk.texto}
            </div>
          </div>
        ))}
        {firstChunk !== undefined && (
          <a
            href={firstChunk.url}
            target="_blank"
            rel="noreferrer"
            className="text-lcsp hover:text-lcsp-deep inline-flex min-h-[44px] items-center text-sm"
          >
            Abrir en el BOE ↗
          </a>
        )}
      </div>
    </aside>
  );
}
