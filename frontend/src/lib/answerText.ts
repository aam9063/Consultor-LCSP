export interface AnswerTextSegment {
  kind: "text";
  text: string;
}

export interface AnswerCitationSegment {
  kind: "citation";
  label: string;
  articulo: string;
  apartado: string | null;
}

export type AnswerSegment = AnswerTextSegment | AnswerCitationSegment;

const CITATION_PATTERN = /\[art\.\s*([^\]\s]+(?:\.[^\]\s.]+)?)\]/g;

function splitReference(reference: string): {
  articulo: string;
  apartado: string | null;
} {
  const dotIndex = reference.indexOf(".");
  if (dotIndex === -1) {
    return { articulo: reference, apartado: null };
  }
  return {
    articulo: reference.slice(0, dotIndex),
    apartado: reference.slice(dotIndex + 1),
  };
}

export function splitAnswer(respuesta: string): AnswerSegment[] {
  const segments: AnswerSegment[] = [];
  let lastIndex = 0;

  for (const match of respuesta.matchAll(CITATION_PATTERN)) {
    const index: number = match.index;
    const reference = match[1];
    if (index > lastIndex) {
      segments.push({ kind: "text", text: respuesta.slice(lastIndex, index) });
    }
    if (reference !== undefined) {
      const { articulo, apartado } = splitReference(reference);
      segments.push({ kind: "citation", label: `art. ${reference}`, articulo, apartado });
    }
    lastIndex = index + match[0].length;
  }

  if (lastIndex < respuesta.length) {
    segments.push({ kind: "text", text: respuesta.slice(lastIndex) });
  }

  return segments;
}

export function citationLabel(citation: {
  articulo: string;
  apartado: string | null;
}): string {
  return citation.apartado === null
    ? `art. ${citation.articulo}`
    : `art. ${citation.articulo}.${citation.apartado}`;
}
