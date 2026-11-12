import { useQuery } from "@tanstack/react-query";

import { fetchHealth } from "../lib/api";

function ApiStatus() {
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth, retry: 0 });

  if (health.isPending) {
    return <span className="text-ink-muted text-sm">Comprobando API…</span>;
  }

  if (health.isError) {
    return (
      <span className="text-decision-nogo text-sm" role="status">
        API no disponible
      </span>
    );
  }

  return (
    <span className="text-lcsp text-sm" role="status">
      API conectada
    </span>
  );
}

export function App() {
  return (
    <div className="bg-canvas text-ink min-h-screen">
      <header className="border-subtle bg-surface border-b">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <h1 className="font-display text-xl font-semibold tracking-tight">
            Consultor LCSP
          </h1>
          <ApiStatus />
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-10">
        <p className="text-ink-muted max-w-2xl text-base">
          Respuestas sobre la Ley 9/2017, de Contratos del Sector Público, con el artículo
          citado en cada afirmación.
        </p>
      </main>

      <footer className="text-ink-muted mx-auto max-w-5xl px-6 py-8 text-xs">
        Esta herramienta no es asesoramiento jurídico. Verifica siempre el texto
        consolidado en el BOE.
      </footer>
    </div>
  );
}
