import { useState, useEffect, useRef } from "react";

/**
 * TextBlockEditor — 單一文字區塊的清單項目
 *
 * 互動模式：
 * - 預設顯示模式：跟其他類型區塊一樣顯示徽章 + 內容預覽
 * - 點擊「編輯」或雙擊內容區，切換成 <textarea> 輸入框
 * - Enter（不含 Shift）或失焦時自動存檔；Escape 取消並還原原內容
 * - 存檔中顯示「儲存中…」，失敗則顯示錯誤並保留輸入框讓使用者重試
 *
 * 設計理由：
 * cid 編碼異常／OCR 辨識的區塊最需要被修正，這裡刻意讓「編輯」
 * 動作輕量（不需要另開彈窗），符合「快速對照左側原圖、隨手修正」
 * 的使用情境。
 *
 * Props:
 *   blockId: string
 *   block: { type, content, encoding_warning, ocr_used, ocr_low_confidence }
 *   isActive: boolean
 *   validation: object | undefined
 *   onActivate: () => void          — 點選整列時觸發（同步左側高亮）
 *   onSave: (content: string) => Promise<void>  — 呼叫 doc.patchText
 */
export default function TextBlockEditor({
  blockId,
  block,
  isActive,
  validation,
  onActivate,
  onSave,
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(block.content || "");
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const textareaRef = useRef(null);

  // block.content 從外部更新時（例如重新上傳、其他操作觸發 reload），
  // 若目前不在編輯狀態，同步更新草稿，避免顯示過期內容。
  useEffect(() => {
    if (!isEditing) setDraft(block.content || "");
  }, [block.content, isEditing]);

  // 進入編輯模式時自動聚焦並選取全部文字，方便直接覆寫
  useEffect(() => {
    if (isEditing && textareaRef.current) {
      textareaRef.current.focus();
      textareaRef.current.select();
    }
  }, [isEditing]);

  const startEdit = (e) => {
    e.stopPropagation();
    setSaveError(null);
    setDraft(block.content || "");
    setIsEditing(true);
  };

  const cancelEdit = () => {
    setDraft(block.content || "");
    setSaveError(null);
    setIsEditing(false);
  };

  const commitEdit = async () => {
    if (draft === block.content) {
      setIsEditing(false);
      return;
    }
    setIsSaving(true);
    setSaveError(null);
    try {
      await onSave(draft);
      setIsEditing(false);
    } catch (err) {
      setSaveError(err.message || "儲存失敗，請重試");
    } finally {
      setIsSaving(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      commitEdit();
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancelEdit();
    }
  };

  return (
    <li
      className={`block-item block-item-text${isActive ? " block-item-active" : ""}${
        isEditing ? " block-item-editing" : ""
      }`}
      onClick={!isEditing ? onActivate : undefined}
    >
      <div className="block-item-row">
        <span className="block-type-badge">{block.type}</span>

        {isEditing ? (
          <textarea
            ref={textareaRef}
            className="block-text-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={handleKeyDown}
            onBlur={commitEdit}
            onClick={(e) => e.stopPropagation()}
            disabled={isSaving}
            rows={Math.min(Math.max(draft.length / 30, 1), 5)}
          />
        ) : (
          <span
            className="block-preview block-preview-editable"
            onDoubleClick={startEdit}
            title="雙擊編輯，或點右側「編輯」按鈕"
          >
            {block.content || "（無內容）"}
          </span>
        )}

        {!isEditing && (
          <button
            type="button"
            className="block-edit-btn"
            onClick={startEdit}
            aria-label="編輯文字內容"
          >
            編輯
          </button>
        )}

        {isSaving && <span className="block-saving-hint">儲存中…</span>}
      </div>

      {saveError && <div className="block-save-error">{saveError}</div>}

      <div className="block-badges">
        {validation && !validation.is_valid && (
          <span className="validation-badge validation-error">
            {validation.error_count} 項錯誤
          </span>
        )}
        {block.encoding_warning && !block.ocr_low_confidence && (
          <span
            className="validation-badge encoding-warning"
            title="此區塊文字因 PDF 字型缺少編碼對照表而無法解析，OCR 辨識亦失敗，請人工確認內容"
          >
            ⚠ 編碼異常
          </span>
        )}
        {block.ocr_low_confidence && (
          <span
            className="validation-badge ocr-low-confidence"
            title="OCR 已嘗試辨識但結果可能不可靠（內容看起來像雜訊），請務必人工核對並修正"
          >
            ⚠ OCR 結果可疑
          </span>
        )}
        {block.ocr_used && !block.ocr_low_confidence && (
          <span
            className="validation-badge ocr-used"
            title="原始文字編碼異常，此內容已透過 OCR 重新辨識，建議仍人工核對正確性"
          >
            🔍 OCR 辨識{isEditing ? "（編輯後將清除此標記）" : ""}
          </span>
        )}
      </div>
    </li>
  );
}
