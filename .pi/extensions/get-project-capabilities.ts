import { Type } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type OpenApiOperation = {
  operationId?: string;
  summary?: string;
  tags?: string[];
  requestBody?: {
    content?: Record<string, { schema?: unknown }>;
  };
  responses?: Record<
    string,
    {
      content?: Record<string, { schema?: unknown }>;
    }
  >;
};

type OpenApiDocument = {
  openapi?: string;
  info?: { title?: string; version?: string };
  paths?: Record<string, Record<string, OpenApiOperation>>;
  components?: {
    schemas?: Record<
      string,
      { type?: string; properties?: Record<string, unknown>; required?: string[] }
    >;
  };
};

type ApiRequestResult = {
  response: Response;
  payload: unknown;
};

class ApiRequestFailure extends Error {
  constructor(
    readonly kind: "network_error" | "cancelled",
    message: string,
  ) {
    super(message);
    this.name = "ApiRequestFailure";
  }
}

const CATEGORY_TAGS = {
  process_ir: "processes",
  reliability_ir: "reliability",
  runtime: "simulation",
  evaluation: "evaluation",
} as const;

const HTTP_METHODS = new Set([
  "get",
  "post",
  "put",
  "patch",
  "delete",
  "head",
  "options",
]);

function apiBaseUrl(): string {
  return (process.env.RFA_API_BASE_URL || "http://127.0.0.1:8000").replace(
    /\/+$/,
    "",
  );
}

async function requestJson(
  url: string,
  init: RequestInit,
  signal: AbortSignal | undefined,
): Promise<ApiRequestResult> {
  let response: Response;
  try {
    response = await fetch(url, { ...init, signal });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const cancelled =
      signal?.aborted ||
      (error instanceof Error && error.name === "AbortError");
    throw new ApiRequestFailure(
      cancelled ? "cancelled" : "network_error",
      `${cancelled ? "Request cancelled" : "Network request failed"}: ${message}`,
    );
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  return { response, payload };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toolError(details: Record<string, unknown>) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(details, null, 2) }],
    details,
    isError: true,
  };
}

function schemaReferences(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.flatMap(schemaReferences);
  }
  if (typeof value !== "object" || value === null) {
    return [];
  }

  const record = value as Record<string, unknown>;
  const reference = record.$ref;
  const current =
    typeof reference === "string"
      ? [reference.split("/").pop() || reference]
      : [];

  return [
    ...current,
    ...Object.entries(record)
      .filter(([key]) => key !== "$ref")
      .flatMap(([, nested]) => schemaReferences(nested)),
  ];
}

function operationSummary(
  method: string,
  path: string,
  operation: OpenApiOperation,
) {
  const requestSchemas = Object.values(operation.requestBody?.content || {})
    .flatMap((mediaType) => schemaReferences(mediaType.schema))
    .filter((name, index, names) => names.indexOf(name) === index);
  const responseSchemas = Object.entries(operation.responses || {})
    .filter(([status]) => status.startsWith("2"))
    .flatMap(([, response]) =>
      Object.values(response.content || {}).flatMap((mediaType) =>
        schemaReferences(mediaType.schema),
      ),
    )
    .filter((name, index, names) => names.indexOf(name) === index);

  return {
    method: method.toUpperCase(),
    path,
    operation_id: operation.operationId || null,
    summary: operation.summary || null,
    request_schemas: requestSchemas,
    response_schemas: responseSchemas,
  };
}

export default function registerProjectCapabilities(pi: ExtensionAPI) {
  pi.registerTool({
    name: "get_project_capabilities",
    label: "Get Project Capabilities",
    description:
      "Read the running reliability-flow-agent FastAPI OpenAPI document and report only its discovered Process IR, Reliability IR, Runtime, and Evaluation API operations and schemas.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal) {
      const openApiUrl = `${apiBaseUrl()}/openapi.json`;
      const { response, payload } = await requestJson(
        openApiUrl,
        { method: "GET" },
        signal,
      );
      if (!response.ok) {
        throw new Error(
          `FastAPI OpenAPI request failed: HTTP ${response.status} ${response.statusText}; response=${JSON.stringify(payload)}`,
        );
      }

      if (!isRecord(payload) || !isRecord(payload.paths)) {
        throw new Error("FastAPI returned an invalid OpenAPI document");
      }

      const document = payload as OpenApiDocument;
      const endpoints = Object.entries(document.paths || {}).flatMap(
        ([path, pathItem]) =>
          path.startsWith("/api/processes")
            ? Object.entries(pathItem)
                .filter(([method]) => HTTP_METHODS.has(method.toLowerCase()))
                .map(([method, operation]) =>
                  operationSummary(method, path, operation),
                )
            : [],
      );
      const taggedEndpoints = Object.entries(document.paths || {}).flatMap(
        ([path, pathItem]) =>
          path.startsWith("/api/processes")
            ? Object.entries(pathItem)
                .filter(([method]) => HTTP_METHODS.has(method.toLowerCase()))
                .flatMap(([method, operation]) =>
                  (operation.tags || []).map((tag) => ({
                    tag,
                    endpoint: operationSummary(method, path, operation),
                  })),
                )
            : [],
      );
      const categories = Object.fromEntries(
        Object.entries(CATEGORY_TAGS).map(([category, tag]) => [
          category,
          taggedEndpoints
            .filter((item) => item.tag === tag)
            .map((item) => item.endpoint),
        ]),
      );
      const schemaNames = new Set(
        endpoints.flatMap((endpoint) => [
          ...endpoint.request_schemas,
          ...endpoint.response_schemas,
        ]),
      );
      const schemas = Object.fromEntries(
        [...schemaNames]
          .sort()
          .filter((name) => document.components?.schemas?.[name])
          .map((name) => {
            const schema = document.components!.schemas![name];
            return [
              name,
              {
                type: schema.type || null,
                properties: Object.keys(schema.properties || {}),
                required: schema.required || [],
              },
            ];
          }),
      );

      const result = {
        source: openApiUrl,
        openapi_version: document.openapi || null,
        service: document.info || {},
        categories,
        schemas,
      };

      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        details: result,
      };
    },
  });

  pi.registerTool({
    name: "analyze_requirements",
    label: "Analyze Requirements",
    description:
      "Submit a complete structured requirement graph extracted from a long natural-language request. The graph must already be a Process IR blueprint: timed activities are tasks, judgement points are separate duration=null decisions, and decisions have conditional plus default exits. The backend validates the structure and rejects fabricated references.",
    promptSnippet:
      "For long multi-step requests, call analyze_requirements first and then generate Process IR from the exact step and branch ids.",
    promptGuidelines: [
      "List every explicitly named business activity, decision, start and end as a step.",
      "A timed activity is a task. A judgement point is a separate decision with duration null; never mark a timed detection or test as a decision.",
      "A named business phase with internal steps is a subprocess step. Its internal steps use parent_id = the subprocess step id.",
      "A parent branch out of a subprocess uses exit_step_id to identify the child end step that returns to the parent.",
      "Use the exact Process IR node id you will later use for each step, including structural decision nodes and subprocess block ids.",
      "List sequential, conditional, default, failure and loop connections as branches.",
      "Decision exits may only be conditional/default and need at least one of each. Task conditional exits need a default.",
      "Put every missing duration, unclear predicate or unclear target into ambiguities.",
      "If analyze_requirements returns valid=false, fix the analysis and resubmit before validating a Process IR.",
      "If an ambiguity blocks generation, ask the user and do not produce a Process IR yet.",
    ],
    parameters: Type.Object(
      {
        analysis: Type.Object(
          {
            summary: Type.String({
              description: "Short structured summary of the requirement.",
            }),
            steps: Type.Array(
              Type.Object(
                {
                  id: Type.String({
                    description:
                      "Exact Process IR node id matching ^[A-Za-z][A-Za-z0-9_-]{0,63}$.",
                  }),
                  name: Type.String({ description: "Business step name." }),
                  kind: Type.Union([
                    Type.Literal("start"),
                    Type.Literal("task"),
                    Type.Literal("decision"),
                    Type.Literal("end"),
                    Type.Literal("subprocess"),
                  ]),
                  parent_id: Type.Optional(
                    Type.String({
                      description:
                        "Parent subprocess step id; null/omitted for root scope.",
                    }),
                  ),
                  description: Type.Optional(Type.String()),
                  duration: Type.Optional(Type.Number({ minimum: 0 })),
                },
                { additionalProperties: false },
              ),
            ),
            branches: Type.Array(
              Type.Object(
                {
                  id: Type.String(),
                  from_step: Type.String(),
                  to_step: Type.String(),
                  kind: Type.Optional(
                    Type.Union([
                      Type.Literal("normal"),
                      Type.Literal("conditional"),
                      Type.Literal("default"),
                      Type.Literal("failure"),
                    ]),
                  ),
                  condition: Type.Optional(Type.String()),
                  loop: Type.Optional(Type.Boolean()),
                  exit_step_id: Type.Optional(
                    Type.String({
                      description:
                        "For a parent branch from a subprocess step, the child end step id used as its exit.",
                    }),
                  ),
                },
                { additionalProperties: false },
              ),
            ),
            ambiguities: Type.Array(
              Type.Object(
                {
                  id: Type.String(),
                  question: Type.String(),
                  blocks_generation: Type.Optional(Type.Boolean()),
                  options: Type.Optional(Type.Array(Type.String())),
                },
                { additionalProperties: false },
              ),
            ),
          },
          { additionalProperties: false },
        ),
      },
      { additionalProperties: false },
    ),
    async execute(_toolCallId, params, signal) {
      const url = `${apiBaseUrl()}/api/agent/requirements/analyze`;
      try {
        const { response, payload } = await requestJson(
          url,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(params.analysis),
          },
          signal,
        );
        if (!response.ok) {
          const kind = response.status === 422 ? "schema_error" : "http_error";
          return toolError({
            error: {
              kind,
              http_status: response.status,
              status_text: response.statusText,
              url,
            },
            response: payload,
          });
        }
        return {
          content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
          details: payload,
        };
      } catch (error) {
        if (error instanceof ApiRequestFailure) {
          return toolError({
            error: { kind: error.kind, message: error.message, url },
          });
        }
        throw error;
      }
    },
  });

  pi.registerTool({
    name: "validate_process_model",
    label: "Validate Process IR",
    description:
      "Send a complete Process IR spec to the existing FastAPI POST /api/processes/validate endpoint. Return its real validation result; never save the model.",
    promptSnippet:
      "Validate a proposed Process IR by calling the project's FastAPI validator. This tool is read-only and does not save the model.",
    promptGuidelines: [
      "Call validate_process_model for every proposed Process IR before reporting it as valid.",
      "Use the returned valid, content_hash, and issues fields as the source of truth; never treat an HTTP or network error as validation success.",
    ],
    parameters: Type.Object(
      {
        spec: Type.Record(Type.String(), Type.Any(), {
          description:
            "The complete ProcessSpec object to validate against the project's current API schema.",
        }),
      },
      { additionalProperties: false },
    ),
    async execute(_toolCallId, params, signal) {
      const url = `${apiBaseUrl()}/api/processes/validate`;
      let result: ApiRequestResult;
      try {
        result = await requestJson(
          url,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(params.spec),
          },
          signal,
        );
      } catch (error) {
        if (error instanceof ApiRequestFailure) {
          return toolError({
            error: {
              kind: error.kind,
              message: error.message,
              url,
            },
          });
        }
        throw error;
      }

      const { response, payload } = result;
      if (!response.ok) {
        const kind = response.status === 422 ? "schema_error" : "http_error";
        const details = isRecord(payload)
          ? {
              ...payload,
              error: {
                kind,
                http_status: response.status,
                status_text: response.statusText,
                url,
              },
            }
          : {
              error: {
                kind,
                http_status: response.status,
                status_text: response.statusText,
                url,
              },
              response: payload,
            };
        return toolError(details);
      }

      if (!isRecord(payload) || typeof payload.valid !== "boolean") {
        return toolError({
          error: {
            kind: "invalid_response",
            message:
              "FastAPI returned a successful HTTP status without a boolean valid field",
            url,
          },
          response: payload,
        });
      }

      return {
        content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
        details: payload,
      };
    },
  });

  pi.registerTool({
    name: "get_process_ir_schema",
    label: "Get Process IR Schema",
    description:
      "Read the current Process IR JSON Schema from the running FastAPI backend. This is read-only and describes the only supported process-ir/1.0 fields.",
    promptSnippet:
      "Read the real Process IR schema from FastAPI before emitting unusual fields.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal) {
      const url = `${apiBaseUrl()}/api/schemas/process-ir`;
      try {
        const { response, payload } = await requestJson(
          url,
          { method: "GET" },
          signal,
        );
        if (!response.ok) {
          return toolError({
            error: {
              kind: "http_error",
              http_status: response.status,
              status_text: response.statusText,
              url,
            },
            response: payload,
          });
        }
        return {
          content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
          details: payload,
        };
      } catch (error) {
        if (error instanceof ApiRequestFailure) {
          return toolError({
            error: { kind: error.kind, message: error.message, url },
          });
        }
        throw error;
      }
    },
  });

  pi.registerTool({
    name: "get_reliability_ir_schema",
    label: "Get Reliability IR Schema",
    description:
      "Read the current Reliability IR JSON Schema from the running FastAPI backend. This is read-only and preserves the existing reliability-ir/1.0 semantics.",
    promptSnippet:
      "Read the real Reliability IR schema before proposing reliability parameters.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal) {
      const url = `${apiBaseUrl()}/api/schemas/reliability-ir`;
      try {
        const { response, payload } = await requestJson(
          url,
          { method: "GET" },
          signal,
        );
        if (!response.ok) {
          return toolError({
            error: {
              kind: "http_error",
              http_status: response.status,
              status_text: response.statusText,
              url,
            },
            response: payload,
          });
        }
        return {
          content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
          details: payload,
        };
      } catch (error) {
        if (error instanceof ApiRequestFailure) {
          return toolError({
            error: { kind: error.kind, message: error.message, url },
          });
        }
        throw error;
      }
    },
  });

  pi.registerTool({
    name: "list_process_models",
    label: "List Process Models",
    description:
      "List saved Process IR models from the FastAPI backend, including process_id, latest version, content hash, and node/edge counts. Read-only.",
    promptSnippet:
      "Use this when the user refers to a saved model and you need its process_id/version.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal) {
      const url = `${apiBaseUrl()}/api/processes`;
      try {
        const { response, payload } = await requestJson(
          url,
          { method: "GET" },
          signal,
        );
        if (!response.ok) {
          return toolError({
            error: {
              kind: "http_error",
              http_status: response.status,
              status_text: response.statusText,
              url,
            },
            response: payload,
          });
        }
        return {
          content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
          details: payload,
        };
      } catch (error) {
        if (error instanceof ApiRequestFailure) {
          return toolError({
            error: { kind: error.kind, message: error.message, url },
          });
        }
        throw error;
      }
    },
  });

  pi.registerTool({
    name: "get_process_model",
    label: "Get Process Model",
    description:
      "Read a saved Process IR document and its version/content_hash from FastAPI. Use this before proposing a modification to an existing saved model. Read-only.",
    promptSnippet:
      "Read the saved model before modifying it; never guess its process_id, version, or content_hash.",
    parameters: Type.Object(
      {
        process_id: Type.String({
          description: "Saved process id such as proc_0123456789ab.",
        }),
        version: Type.Optional(
          Type.Number({ description: "Optional exact version; default latest." }),
        ),
      },
      { additionalProperties: false },
    ),
    async execute(_toolCallId, params, signal) {
      const suffix =
        typeof params.version === "number" ? `?version=${params.version}` : "";
      const url = `${apiBaseUrl()}/api/processes/${encodeURIComponent(
        params.process_id,
      )}${suffix}`;
      try {
        const { response, payload } = await requestJson(
          url,
          { method: "GET" },
          signal,
        );
        if (!response.ok) {
          return toolError({
            error: {
              kind: "http_error",
              http_status: response.status,
              status_text: response.statusText,
              url,
            },
            response: payload,
          });
        }
        return {
          content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
          details: payload,
        };
      } catch (error) {
        if (error instanceof ApiRequestFailure) {
          return toolError({
            error: { kind: error.kind, message: error.message, url },
          });
        }
        throw error;
      }
    },
  });

  pi.registerTool({
    name: "get_reliability_config",
    label: "Get Reliability Config",
    description:
      "Read the Reliability IR currently bound to a saved Process IR version from FastAPI. Read-only.",
    promptSnippet:
      "Read the current reliability configuration before proposing changes.",
    parameters: Type.Object(
      {
        process_id: Type.String({
          description: "Saved process id such as proc_0123456789ab.",
        }),
        version: Type.Optional(
          Type.Number({ description: "Optional exact Process IR version." }),
        ),
      },
      { additionalProperties: false },
    ),
    async execute(_toolCallId, params, signal) {
      const suffix =
        typeof params.version === "number" ? `?version=${params.version}` : "";
      const url = `${apiBaseUrl()}/api/processes/${encodeURIComponent(
        params.process_id,
      )}/reliability${suffix}`;
      try {
        const { response, payload } = await requestJson(
          url,
          { method: "GET" },
          signal,
        );
        if (!response.ok) {
          return toolError({
            error: {
              kind: "http_error",
              http_status: response.status,
              status_text: response.statusText,
              url,
            },
            response: payload,
          });
        }
        return {
          content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
          details: payload,
        };
      } catch (error) {
        if (error instanceof ApiRequestFailure) {
          return toolError({
            error: { kind: error.kind, message: error.message, url },
          });
        }
        throw error;
      }
    },
  });

  pi.registerTool({
    name: "validate_reliability_model",
    label: "Validate Reliability IR",
    description:
      "Send a complete Reliability IR payload and process_id to the existing FastAPI reliability validator. Return its real result; never save or simulate.",
    promptSnippet:
      "Validate every proposed Reliability IR against the saved Process IR version/hash before reporting it as valid.",
    promptGuidelines: [
      "Call get_process_model first to obtain the exact process_id, version, and content_hash.",
      "Pass the complete ReliabilitySpec as spec, bound to that exact version/hash.",
      "Do not claim success unless the tool returns valid=true.",
      "Do not save reliability configuration from this tool.",
    ],
    parameters: Type.Object(
      {
        process_id: Type.String({
          description: "Saved process id such as proc_0123456789ab.",
        }),
        spec: Type.Record(Type.String(), Type.Any(), {
          description:
            "The complete ReliabilitySpec payload, including process_version, process_hash, and nodes.",
        }),
      },
      { additionalProperties: false },
    ),
    async execute(_toolCallId, params, signal) {
      const url = `${apiBaseUrl()}/api/processes/${encodeURIComponent(
        params.process_id,
      )}/reliability/validate`;
      try {
        const { response, payload } = await requestJson(
          url,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(params.spec),
          },
          signal,
        );
        if (!response.ok) {
          const kind = response.status === 422 ? "schema_error" : "http_error";
          return toolError({
            error: {
              kind,
              http_status: response.status,
              status_text: response.statusText,
              url,
            },
            response: payload,
          });
        }
        if (!isRecord(payload) || typeof payload.valid !== "boolean") {
          return toolError({
            error: {
              kind: "invalid_response",
              message:
                "FastAPI returned a successful HTTP status without a boolean valid field",
              url,
            },
            response: payload,
          });
        }
        return {
          content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
          details: payload,
        };
      } catch (error) {
        if (error instanceof ApiRequestFailure) {
          return toolError({
            error: { kind: error.kind, message: error.message, url },
          });
        }
        throw error;
      }
    },
  });
}
