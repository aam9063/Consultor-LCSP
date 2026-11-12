import { NavLink, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { ConsultaView } from "../features/consulta/ConsultaView";
import { RevisorView } from "../features/revisor/RevisorView";
import { fetchHealth } from "../lib/api";
import type { ConsultaResponse } from "../lib/api";

function navClass({ isActive }: { isActive: boolean }): string {
  return `inline-flex min-h-[44px] items-center rounded-lg px-3.5 py-2.5 ${
    isActive ? "bg-nav-active text-lcsp font-semibold" : "text-ink-soft"
  }`;
}

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
  const [history, setHistory] = useState<ConsultaResponse[]>([]);
  const [activeConsulta, setActiveConsulta] = useState<ConsultaResponse | null>(null);

  function handleConsultaCompleted(consulta: ConsultaResponse) {
    setHistory((previous) => [consulta, ...previous]);
    setActiveConsulta(consulta);
  }

  return (
    <div className="bg-canvas text-ink min-h-screen">
      <header className="border-subtle bg-surface border-b">
        <div className="mx-auto flex max-w-[1360px] flex-wrap items-center gap-6 px-6 py-3.5">
          <div className="flex items-center gap-2.5">
            <svg
              width="28"
              height="28"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
              className="text-lcsp"
            >
              <path d="M12 3v18M5 21h14"></path>
              <path d="M6 7h12"></path>
              <path d="M6 7l-3 7a3 3 0 0 0 6 0z"></path>
              <path d="M18 7l-3 7a3 3 0 0 0 6 0z"></path>
            </svg>
            <h1 className="font-display text-xl font-bold tracking-tight">
              Consultor LCSP
            </h1>
          </div>
          <nav aria-label="Principal" className="flex flex-wrap gap-1">
            <NavLink to="/" end className={navClass}>
              Consulta
            </NavLink>
            <NavLink to="/revisor" className={navClass}>
              Revisor de cláusulas
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-4">
            <span className="text-ink-muted text-[13px]">
              Ley 9/2017 · texto consolidado BOE
            </span>
            <ApiStatus />
          </div>
        </div>
      </header>

      <div className="bg-notice-bg border-notice-border text-notice-text border-b text-[13px]">
        <div className="mx-auto max-w-[1360px] px-6 py-2">
          Herramienta de apoyo. No es asesoramiento jurídico: comprueba siempre el
          artículo citado.
        </div>
      </div>

      <Routes>
        <Route
          path="/"
          element={
            <ConsultaView
              history={history}
              activeConsulta={activeConsulta}
              onSelectHistory={setActiveConsulta}
              onConsultaCompleted={handleConsultaCompleted}
            />
          }
        />
        <Route path="/revisor" element={<RevisorView />} />
      </Routes>

      <footer className="text-ink-muted mx-auto max-w-[1360px] px-6 py-8 text-xs">
        Esta herramienta no es asesoramiento jurídico. Verifica siempre el texto
        consolidado en el BOE.
      </footer>
    </div>
  );
}
