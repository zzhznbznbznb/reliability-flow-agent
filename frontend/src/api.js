export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }
  if (!response.ok) {
    const detail = payload && payload.detail;
    const message =
      (typeof detail === "string" ? detail : null) ||
      (detail && typeof detail === "object" && typeof detail.message === "string"
        ? detail.message
        : null) ||
      `请求失败 (${response.status})`;
    throw new ApiError(message, response.status, payload);
  }
  return payload;
}

export const api = {
  health: () => request("/health"),
  meta: () => request("/api/meta"),
  listProcesses: () => request("/api/processes"),
  getProcess: (processId, version = null) =>
    request(
      `/api/processes/${encodeURIComponent(processId)}${
        version ? `?version=${version}` : ""
      }`,
    ),
  getVersions: (processId) =>
    request(`/api/processes/${encodeURIComponent(processId)}/versions`),
  createProcess: (spec) =>
    request("/api/processes", {
      method: "POST",
      body: JSON.stringify(spec),
    }),
  updateProcess: (processId, baseVersion, spec) =>
    request(`/api/processes/${encodeURIComponent(processId)}`, {
      method: "PUT",
      body: JSON.stringify({ base_version: baseVersion, process: spec }),
    }),
  validate: (spec) =>
    request("/api/processes/validate", {
      method: "POST",
      body: JSON.stringify(spec),
    }),
  getReliability: (processId, version = null) =>
    request(
      `/api/processes/${encodeURIComponent(processId)}/reliability${
        version ? `?version=${version}` : ""
      }`,
    ),
  saveReliability: (processId, payload) =>
    request(`/api/processes/${encodeURIComponent(processId)}/reliability`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  validateReliability: (processId, payload) =>
    request(
      `/api/processes/${encodeURIComponent(processId)}/reliability/validate`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),
  getReliabilityHistory: (processId) =>
    request(
      `/api/processes/${encodeURIComponent(processId)}/reliability/history`,
    ),
  simulate: (processId, payload) =>
    request(`/api/processes/${encodeURIComponent(processId)}/simulate`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  simulateAndEvaluate: (processId, payload) =>
    request(
      `/api/processes/${encodeURIComponent(processId)}/simulate/evaluate`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),
  runExperiment: (processId, payload) =>
    request(`/api/processes/${encodeURIComponent(processId)}/experiments`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listExperiments: () => request("/api/experiments"),
  getExperiment: (resultId) =>
    request(`/api/experiments/${encodeURIComponent(resultId)}`),
  agentHealth: () => request("/api/agent/health"),
  createAgentSession: () =>
    request("/api/agent/sessions", {
      method: "POST",
      body: JSON.stringify({}),
    }),
  getAgentSession: (sessionId) =>
    request(`/api/agent/sessions/${encodeURIComponent(sessionId)}`),
  sendAgentMessage: (sessionId, message, context = null) =>
    request(`/api/agent/sessions/${encodeURIComponent(sessionId)}/messages`, {
      method: "POST",
      body: JSON.stringify({ message, context }),
    }),
  cancelAgentTask: (sessionId) =>
    request(`/api/agent/sessions/${encodeURIComponent(sessionId)}/cancel`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  recordAgentSimulationResult: (sessionId, resultId) =>
    request(
      `/api/agent/sessions/${encodeURIComponent(sessionId)}/simulation-results`,
      {
        method: "POST",
        body: JSON.stringify({ result_id: resultId }),
      },
    ),
  deleteAgentSession: (sessionId) =>
    request(`/api/agent/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
    }),
  agentEventsUrl: (sessionId) =>
    `/api/agent/sessions/${encodeURIComponent(sessionId)}/events`,
};

export function issuesFromError(error) {
  const payload = error && error.payload;
  if (payload && Array.isArray(payload.issues)) return payload.issues;
  if (payload && payload.detail && Array.isArray(payload.detail.issues)) {
    return payload.detail.issues;
  }
  return [];
}
