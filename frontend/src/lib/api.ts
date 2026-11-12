export interface HealthStatus {
  status: string;
}

export interface Citation {
  articulo: string;
  apartado: string | null;
}

export interface ScoredChunk {
  id: number;
  articulo: string;
  apartado: string | null;
  titulo: string;
  url: string;
  texto: string;
  score: number;
  branches: string[];
}

export interface ConsultaResponse {
  pregunta: string;
  respuesta: string;
  citas: Citation[];
  abstencion: boolean;
  motivo_abstencion: string | null;
  advertencia: string | null;
  afirmaciones_no_respaldadas: string[];
  modelo: string;
  chunks: ScoredChunk[];
}

export interface ArticleChunk {
  id: number;
  articulo: string;
  apartado: string | null;
  titulo: string;
  url: string;
  texto: string;
}

export interface ArticleResponse {
  articulo: string;
  chunks: ArticleChunk[];
}

export interface Aviso {
  tipo: string;
  explicacion: string;
  articulos_citados: Citation[];
  cita_de_la_clausula: string;
}

export interface AvisoInvalido {
  tipo: string | null;
  explicacion: string | null;
  cita_de_la_clausula: string | null;
  articulos_citados: string[];
  motivos: string[];
}

export interface RevisionResponse {
  clausula: string;
  avisos: Aviso[];
  avisos_invalidos: AvisoInvalido[];
  sin_observaciones: boolean;
  observaciones: string | null;
  modelo: string;
  chunks: ScoredChunk[];
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

const API_BASE_URL = import.meta.env.VITE_API_URL ?? "/api";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isStringOrNull(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString);
}

function isCitation(value: unknown): value is Citation {
  return isRecord(value) && isString(value.articulo) && isStringOrNull(value.apartado);
}

function isCitationArray(value: unknown): value is Citation[] {
  return Array.isArray(value) && value.every(isCitation);
}

function isScoredChunk(value: unknown): value is ScoredChunk {
  return (
    isRecord(value) &&
    typeof value.id === "number" &&
    isString(value.articulo) &&
    isStringOrNull(value.apartado) &&
    isString(value.titulo) &&
    isString(value.url) &&
    isString(value.texto) &&
    typeof value.score === "number" &&
    isStringArray(value.branches)
  );
}

function isScoredChunkArray(value: unknown): value is ScoredChunk[] {
  return Array.isArray(value) && value.every(isScoredChunk);
}

function isArticleChunk(value: unknown): value is ArticleChunk {
  return (
    isRecord(value) &&
    typeof value.id === "number" &&
    isString(value.articulo) &&
    isStringOrNull(value.apartado) &&
    isString(value.titulo) &&
    isString(value.url) &&
    isString(value.texto)
  );
}

function isConsultaResponse(payload: unknown): payload is ConsultaResponse {
  return (
    isRecord(payload) &&
    isString(payload.pregunta) &&
    isString(payload.respuesta) &&
    isCitationArray(payload.citas) &&
    typeof payload.abstencion === "boolean" &&
    isStringOrNull(payload.motivo_abstencion) &&
    isStringOrNull(payload.advertencia) &&
    isStringArray(payload.afirmaciones_no_respaldadas) &&
    isString(payload.modelo) &&
    isScoredChunkArray(payload.chunks)
  );
}

function isArticleResponse(payload: unknown): payload is ArticleResponse {
  return (
    isRecord(payload) &&
    isString(payload.articulo) &&
    Array.isArray(payload.chunks) &&
    payload.chunks.every(isArticleChunk)
  );
}

function isAviso(value: unknown): value is Aviso {
  return (
    isRecord(value) &&
    isString(value.tipo) &&
    isString(value.explicacion) &&
    isCitationArray(value.articulos_citados) &&
    isString(value.cita_de_la_clausula)
  );
}

function isAvisoInvalido(value: unknown): value is AvisoInvalido {
  return (
    isRecord(value) &&
    isStringOrNull(value.tipo) &&
    isStringOrNull(value.explicacion) &&
    isStringOrNull(value.cita_de_la_clausula) &&
    isStringArray(value.articulos_citados) &&
    isStringArray(value.motivos)
  );
}

function isRevisionResponse(payload: unknown): payload is RevisionResponse {
  return (
    isRecord(payload) &&
    isString(payload.clausula) &&
    Array.isArray(payload.avisos) &&
    payload.avisos.every(isAviso) &&
    Array.isArray(payload.avisos_invalidos) &&
    payload.avisos_invalidos.every(isAvisoInvalido) &&
    typeof payload.sin_observaciones === "boolean" &&
    isStringOrNull(payload.observaciones) &&
    isString(payload.modelo) &&
    isScoredChunkArray(payload.chunks)
  );
}

function isHealthStatus(payload: unknown): payload is HealthStatus {
  return isRecord(payload) && isString(payload.status);
}

function isTypedErrorEnvelope(
  payload: unknown,
): payload is { error: { code: string; message: string } } {
  return (
    isRecord(payload) &&
    isRecord(payload.error) &&
    isString(payload.error.code) &&
    isString(payload.error.message)
  );
}

async function fetchJson(url: string, init?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new ApiError(0, "network", "No se pudo contactar con la API.");
  }

  const payload: unknown = await response.json().catch(() => undefined);

  if (!response.ok) {
    if (isTypedErrorEnvelope(payload)) {
      throw new ApiError(response.status, payload.error.code, payload.error.message);
    }
    throw new ApiError(
      response.status,
      "unexpected_error",
      `La API respondió ${String(response.status)}.`,
    );
  }

  if (payload === undefined) {
    throw new ApiError(
      0,
      "invalid_response",
      "La API devolvió una respuesta vacía o no JSON.",
    );
  }

  return payload;
}

async function postJson<T>(
  path: string,
  body: Record<string, string>,
  validate: (payload: unknown) => payload is T,
  invalidMessage: string,
): Promise<T> {
  const payload = await fetchJson(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!validate(payload)) {
    throw new ApiError(0, "invalid_response", invalidMessage);
  }
  return payload;
}

export async function fetchHealth(): Promise<HealthStatus> {
  const payload = await fetchJson(`${API_BASE_URL}/health`);
  if (!isHealthStatus(payload)) {
    throw new ApiError(
      0,
      "invalid_response",
      "Health check returned an unexpected payload",
    );
  }
  return payload;
}

export async function postConsulta(pregunta: string): Promise<ConsultaResponse> {
  return postJson(
    "/consultas",
    { pregunta },
    isConsultaResponse,
    "Respuesta de consulta con formato inesperado.",
  );
}

export async function postRevision(clausula: string): Promise<RevisionResponse> {
  return postJson(
    "/revisiones",
    { clausula },
    isRevisionResponse,
    "Respuesta de revisión con formato inesperado.",
  );
}

export async function fetchArticulo(numero: string): Promise<ArticleResponse> {
  const payload = await fetchJson(
    `${API_BASE_URL}/articulos/${encodeURIComponent(numero)}`,
  );
  if (!isArticleResponse(payload)) {
    throw new ApiError(
      0,
      "invalid_response",
      "Respuesta de artículo con formato inesperado.",
    );
  }
  return payload;
}
