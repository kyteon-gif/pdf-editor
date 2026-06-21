/**
 * api/client.js — 集中管理所有與 Flask 後端的通訊
 *
 * 對應後端路由：
 *   POST   /api/upload
 *   GET    /api/doc/:id
 *   GET    /api/doc/:id/block/:blockId
 *   PATCH  /api/doc/:id/block/:blockId
 *   GET    /api/doc/:id/overview
 *   POST   /api/doc/:id/image/:blockId/replace
 *   PATCH  /api/doc/:id/image/:blockId/transform
 *   POST   /api/doc/:id/image/:blockId/restore
 *   GET    /api/doc/:id/image/:blockId
 *   POST   /api/doc/:id/export
 *   GET    /api/doc/:id/export/latest
 */

const BASE = "/api";

/** 統一錯誤處理：非 2xx 回應一律拋出帶訊息的 Error。 */
async function handleResponse(res) {
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body.error) message = body.error;
    } catch {
      /* 回應本身不是 JSON（例如 PDF 串流），略過 */
    }
    throw new Error(message);
  }
  return res;
}

// ── 上傳 ──────────────────────────────────────────────────────

export async function uploadPdf(file, onProgress) {
  const form = new FormData();
  form.append("pdf", file);

  const res = await fetch(`${BASE}/upload`, {
    method: "POST",
    body: form,
  });
  await handleResponse(res);
  return res.json();
}

// ── 文件 / 區塊讀取 ──────────────────────────────────────────

export async function getDocument(docId) {
  const res = await fetch(`${BASE}/doc/${docId}`);
  await handleResponse(res);
  return res.json();
}

/** 回傳原始 PDF 的 URL，供 pdf.js 的 getDocument() 直接載入。 */
export function rawPdfUrl(docId) {
  return `${BASE}/doc/${docId}/raw`;
}

export async function getBlock(docId, blockId) {
  const res = await fetch(`${BASE}/doc/${docId}/block/${blockId}`);
  await handleResponse(res);
  return res.json();
}

export async function getOverview(docId) {
  const res = await fetch(`${BASE}/doc/${docId}/overview`);
  await handleResponse(res);
  return res.json();
}

// ── 區塊更新（文字 / 表格）────────────────────────────────────

/**
 * @param {string} docId
 * @param {string} blockId
 * @param {"text"|"table"|"image"} type
 * @param {object} data - 依 type 不同欄位不同
 * @returns {Promise<{ok: boolean, block: object, validation?: object}>}
 */
export async function patchBlock(docId, blockId, type, data) {
  const res = await fetch(`${BASE}/doc/${docId}/block/${blockId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, data }),
  });
  await handleResponse(res);
  return res.json();
}

// ── 圖片 ──────────────────────────────────────────────────────

export async function replaceImage(docId, blockId, file, extra = {}) {
  const form = new FormData();
  form.append("image", file);
  for (const [key, val] of Object.entries(extra)) {
    form.append(key, String(val));
  }
  const res = await fetch(`${BASE}/doc/${docId}/image/${blockId}/replace`, {
    method: "POST",
    body: form,
  });
  await handleResponse(res);
  return res.json();
}

export async function transformImage(docId, blockId, transform) {
  const res = await fetch(`${BASE}/doc/${docId}/image/${blockId}/transform`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(transform),
  });
  await handleResponse(res);
  return res.json();
}

export async function restoreImage(docId, blockId) {
  const res = await fetch(`${BASE}/doc/${docId}/image/${blockId}/restore`, {
    method: "POST",
  });
  await handleResponse(res);
  return res.json();
}

export function imageUrl(docId, blockId) {
  // 直接回傳 URL 供 <img src> 使用，並加時間戳避免瀏覽器快取置換後的圖片
  return `${BASE}/doc/${docId}/image/${blockId}?t=${Date.now()}`;
}

// ── 匯出 ──────────────────────────────────────────────────────

export async function exportPdf(docId) {
  const res = await fetch(`${BASE}/doc/${docId}/export`, { method: "POST" });
  await handleResponse(res);
  return res.blob();
}

export async function getLatestExport(docId) {
  const res = await fetch(`${BASE}/doc/${docId}/export/latest`);
  await handleResponse(res);
  return res.blob();
}

/** 觸發瀏覽器下載 blob。 */
export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
