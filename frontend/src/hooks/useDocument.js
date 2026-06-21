import { useState, useCallback, useRef } from "react";
import {
  uploadPdf,
  getDocument,
  patchBlock as apiPatchBlock,
  replaceImage as apiReplaceImage,
  transformImage as apiTransformImage,
  restoreImage as apiRestoreImage,
  exportPdf,
  downloadBlob,
} from "../api/client";

/**
 * useDocument — 整份文件的編輯狀態與所有變更操作
 *
 * 狀態形狀對齊後端 CacheManager.load() / GET /api/doc/:id 的回應：
 *   { docId, filename, pageCount, structure, texts, tables, meta }
 *
 * 設計原則：
 * - 所有寫入操作（patchText/patchTable/replaceImage...）都是「樂觀更新」：
 *   先更新本地 state 讓 UI 立即反應，若後端回傳失敗則回滾。
 * - validation 結果（表格 PATCH 後）獨立存在 validationByBlock，
 *   讓 UI 可以針對單一表格顯示警示，不需要全文件重新驗證。
 * - dirty 集合記錄「已修改但尚未確認後端成功」的 block id，
 *   供 Toolbar 顯示「有未儲存變更」提示（雖然每次 patch 都即時送出，
 *   dirty 在此處用來標示「最近一次操作是否成功」）。
 */
export function useDocument() {
  const [docId, setDocId] = useState(null);
  const [filename, setFilename] = useState("");
  const [pageCount, setPageCount] = useState(0);
  const [structure, setStructure] = useState([]);
  const [texts, setTexts] = useState({});
  const [tables, setTables] = useState({});
  const [meta, setMeta] = useState(null);

  const [validationByBlock, setValidationByBlock] = useState({});
  const [activeBlockId, setActiveBlockId] = useState(null);

  const [isUploading, setIsUploading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [error, setError] = useState(null);

  // 上傳時後端可能回傳 base64 圖片（首次解析），暫存供 PdfViewer 初次渲染使用
  const [initialImages, setInitialImages] = useState({});

  const resetError = useCallback(() => setError(null), []);

  // ── 取得區塊（文字或表格）的小工具 ────────────────────────
  const getBlock = useCallback(
    (blockId) => texts[blockId] || tables[blockId] || null,
    [texts, tables]
  );

  // ── 上傳 ──────────────────────────────────────────────────
  const upload = useCallback(async (file) => {
    setIsUploading(true);
    setError(null);
    try {
      const data = await uploadPdf(file);
      setDocId(data.doc_id);
      setFilename(data.filename);
      setPageCount(data.page_count);
      setStructure(data.structure);
      setTexts(data.texts);
      setTables(data.tables);
      setInitialImages(data.images || {});
      setValidationByBlock({});
      setActiveBlockId(data.structure?.[0] ?? null);
      return data;
    } catch (e) {
      setError(e.message);
      throw e;
    } finally {
      setIsUploading(false);
    }
  }, []);

  // ── 重新載入（例如快取命中時，或需要強制刷新）──────────────
  const reload = useCallback(async (id) => {
    setError(null);
    try {
      const data = await getDocument(id);
      setDocId(data.doc_id);
      setFilename(data.filename);
      setPageCount(data.page_count);
      setStructure(data.structure);
      setTexts(data.texts);
      setTables(data.tables);
      setMeta(data.meta);
      return data;
    } catch (e) {
      setError(e.message);
      throw e;
    }
  }, []);

  // ── 文字區塊更新 ──────────────────────────────────────────
  const patchText = useCallback(
    async (blockId, content) => {
      if (!docId) return;
      const prev = texts[blockId];
      // 樂觀更新
      setTexts((t) => ({
        ...t,
        [blockId]: { ...t[blockId], content },
      }));
      setIsSaving(true);
      try {
        const res = await apiPatchBlock(docId, blockId, "text", { content });
        setTexts((t) => ({ ...t, [blockId]: res.block }));
      } catch (e) {
        // 回滾
        setTexts((t) => ({ ...t, [blockId]: prev }));
        setError(e.message);
        throw e;
      } finally {
        setIsSaving(false);
      }
    },
    [docId, texts]
  );

  // ── 表格區塊更新（raw_rows / total）──────────────────────
  const patchTable = useCallback(
    async (blockId, data) => {
      if (!docId) return;
      const prev = tables[blockId];
      setTables((t) => ({
        ...t,
        [blockId]: { ...t[blockId], ...data },
      }));
      setIsSaving(true);
      try {
        const res = await apiPatchBlock(docId, blockId, "table", data);
        setTables((t) => ({ ...t, [blockId]: res.block }));
        if (res.validation) {
          setValidationByBlock((v) => ({ ...v, [blockId]: res.validation }));
        }
        return res;
      } catch (e) {
        setTables((t) => ({ ...t, [blockId]: prev }));
        setError(e.message);
        throw e;
      } finally {
        setIsSaving(false);
      }
    },
    [docId, tables]
  );

  // ── 圖片置換 ──────────────────────────────────────────────
  const replaceImage = useCallback(
    async (blockId, file, extra = {}) => {
      if (!docId) return;
      setIsSaving(true);
      try {
        const res = await apiReplaceImage(docId, blockId, file, extra);
        setTexts((t) => ({ ...t, [blockId]: res.block }));
        return res;
      } catch (e) {
        setError(e.message);
        throw e;
      } finally {
        setIsSaving(false);
      }
    },
    [docId]
  );

  // ── 圖片尺寸/位置調整 ──────────────────────────────────────
  const transformImage = useCallback(
    async (blockId, transform) => {
      if (!docId) return;
      const prev = texts[blockId];
      setTexts((t) => ({ ...t, [blockId]: { ...t[blockId], ...transform } }));
      setIsSaving(true);
      try {
        const res = await apiTransformImage(docId, blockId, transform);
        setTexts((t) => ({ ...t, [blockId]: res.block }));
      } catch (e) {
        setTexts((t) => ({ ...t, [blockId]: prev }));
        setError(e.message);
        throw e;
      } finally {
        setIsSaving(false);
      }
    },
    [docId, texts]
  );

  // ── 還原原圖 ──────────────────────────────────────────────
  const restoreImage = useCallback(
    async (blockId) => {
      if (!docId) return;
      setIsSaving(true);
      try {
        await apiRestoreImage(docId, blockId);
      } catch (e) {
        setError(e.message);
        throw e;
      } finally {
        setIsSaving(false);
      }
    },
    [docId]
  );

  // ── 匯出 ──────────────────────────────────────────────────
  const doExport = useCallback(async () => {
    if (!docId) return;
    setIsExporting(true);
    setError(null);
    try {
      const blob = await exportPdf(docId);
      const stem = filename.replace(/\.pdf$/i, "");
      downloadBlob(blob, `${stem}_export.pdf`);
    } catch (e) {
      setError(e.message);
      throw e;
    } finally {
      setIsExporting(false);
    }
  }, [docId, filename]);

  return {
    // 狀態
    docId,
    filename,
    pageCount,
    structure,
    texts,
    tables,
    meta,
    initialImages,
    validationByBlock,
    activeBlockId,
    isUploading,
    isSaving,
    isExporting,
    error,

    // 操作
    upload,
    reload,
    patchText,
    patchTable,
    replaceImage,
    transformImage,
    restoreImage,
    doExport,
    setActiveBlockId,
    getBlock,
    resetError,
  };
}
