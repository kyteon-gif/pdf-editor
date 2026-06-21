import { useRef, useMemo } from "react";
import { useDocument } from "./hooks/useDocument";
import PdfViewer, { buildBlocksByPage } from "./components/PdfViewer";
import TextBlockEditor from "./components/TextBlockEditor";

/**
 * App — 左右分割主框架
 *
 * 左側：PDF 預覽（pdf.js canvas，待 PdfViewer 元件完成後接入）
 * 右側：結構化編輯面板（依 structure 順序列出每個區塊）
 *
 * 目前狀態：骨架版本。
 * - 上傳 / 區塊清單 / 點選同步高亮 已可運作
 * - 實際的文字/表格/圖片編輯 UI 由後續元件（TextBlockEditor 等）取代目前的 placeholder
 * - PdfViewer 元件完成後，左側會替換成真正的 canvas 渲染
 */
export default function App() {
  const doc = useDocument();
  const fileInputRef = useRef(null);

  const blocksByPage = useMemo(
    () => buildBlocksByPage(doc.structure, doc.texts, doc.tables),
    [doc.structure, doc.texts, doc.tables]
  );

  const handleFileChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      await doc.upload(file);
    } catch {
      // error 已存在 doc.error，交由下方 banner 顯示
    } finally {
      e.target.value = "";
    }
  };

  const handleExport = async () => {
    try {
      await doc.doExport();
    } catch {
      /* error 已存在 doc.error */
    }
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>PDF 智慧編輯器</h1>
        <div className="app-header-actions">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={doc.isUploading}
          >
            {doc.isUploading ? "解析中…" : "上傳 PDF"}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf"
            style={{ display: "none" }}
            onChange={handleFileChange}
          />
          <button
            type="button"
            onClick={handleExport}
            disabled={!doc.docId || doc.isExporting}
          >
            {doc.isExporting ? "匯出中…" : "匯出 PDF"}
          </button>
          {doc.isSaving && <span className="saving-indicator">儲存中…</span>}
        </div>
      </header>

      {doc.error && (
        <div className="error-banner" role="alert">
          {doc.error}
          <button type="button" onClick={doc.resetError}>
            關閉
          </button>
        </div>
      )}

      {!doc.docId ? (
        <EmptyState onUploadClick={() => fileInputRef.current?.click()} />
      ) : (
        <main className="split-pane">
          <section className="pane pane-left" aria-label="PDF 預覽">
            <PdfViewer
              docId={doc.docId}
              pageCount={doc.pageCount}
              blocksByPage={blocksByPage}
              activeBlockId={doc.activeBlockId}
              onBlockClick={doc.setActiveBlockId}
            />
          </section>

          <section className="pane pane-right" aria-label="編輯面板">
            <EditorPanelPlaceholder doc={doc} />
          </section>
        </main>
      )}
    </div>
  );
}

// ── 暫時元件（待後續步驟拆成獨立檔案並實作完整功能）──────────

function EmptyState({ onUploadClick }) {
  return (
    <div className="empty-state">
      <p>尚未上傳文件</p>
      <button type="button" onClick={onUploadClick}>
        選擇 PDF 檔案
      </button>
    </div>
  );
}

function EditorPanelPlaceholder({ doc }) {
  // 文字類型的區塊（含 cover/heading/body/appendix/overview 等）
  // 走可編輯的 TextBlockEditor；表格與圖片暫維持唯讀預覽，
  // 待後續步驟分別實作 TableBlockEditor / ImageBlockEditor。
  const TEXT_LIKE_TYPES = new Set([
    "cover",
    "heading_1",
    "heading_2",
    "body",
    "appendix",
    "overview",
    "unknown",
  ]);

  return (
    <div className="editor-panel-placeholder">
      <ul className="block-list">
        {doc.structure.map((blockId) => {
          const block = doc.getBlock(blockId);
          if (!block) return null;
          const isActive = blockId === doc.activeBlockId;
          const validation = doc.validationByBlock[blockId];

          const isTextLike =
            TEXT_LIKE_TYPES.has(block.type) && block.raw_rows === undefined;

          if (isTextLike) {
            return (
              <TextBlockEditor
                key={blockId}
                blockId={blockId}
                block={block}
                isActive={isActive}
                validation={validation}
                onActivate={() => doc.setActiveBlockId(blockId)}
                onSave={(content) => doc.patchText(blockId, content)}
              />
            );
          }

          // ── 表格 / 圖片：暫時維持唯讀預覽 ──────────────────
          return (
            <li
              key={blockId}
              className={`block-item${isActive ? " block-item-active" : ""}`}
              onClick={() => doc.setActiveBlockId(blockId)}
            >
              <span className="block-type-badge">{block.type}</span>
              <span className="block-preview">
                {block.raw_rows
                  ? `表格（${block.raw_rows.length} 列）`
                  : block.content
                  ? block.content.slice(0, 40)
                  : "（無內容）"}
              </span>
              {validation && !validation.is_valid && (
                <span className="validation-badge validation-error">
                  {validation.error_count} 項錯誤
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
