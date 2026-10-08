export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(`/api${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch {
    throw new ApiError("Cannot reach the server. Is the backend running on port 8000?", 0);
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    /* empty or non-JSON body */
  }
  if (!res.ok) {
    const d = data?.detail;
    let message = `Request failed (${res.status})`;
    if (typeof d === "string") message = d;
    else if (d?.message) message = d.message;
    else if (Array.isArray(d)) message = d.map((x) => x.msg).join("; ");
    throw new ApiError(message, res.status);
  }
  return data;
}

const post = (path, body) => request(path, { method: "POST", body: JSON.stringify(body ?? {}) });

export const api = {
  health: () => request("/health"),
  listReports: () => request("/reports"),
  createReport: (body) => post("/reports", body),
  getReport: (id) => request(`/reports/${id}`),
  triage: (id) => post(`/reports/${id}/triage`),
  triageRuns: (id) => request(`/reports/${id}/triage-runs`),
  workOrders: (id) => request(`/reports/${id}/work-orders`),
  editWorkOrder: (id, body) => request(`/work-orders/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  approve: (id, decided_by) => post(`/work-orders/${id}/approve`, { decided_by }),
  reject: (id, decided_by, reason) => post(`/work-orders/${id}/reject`, { decided_by, reason }),
  addFinding: (reportId, body) => post(`/reports/${reportId}/findings`, body),
  confirmFinding: (id, confirmed_by, notes) => post(`/findings/${id}/confirm`, { confirmed_by, notes }),
  listEquipment: () => request("/equipment"),
  history: (id) => request(`/equipment/${id}/history`),
};
