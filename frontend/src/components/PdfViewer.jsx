import { useEffect, useRef, useState, useCallback } from "react";
import * as pdfjsLib from "pdfjs-dist";
import { rawPdfUrl } from "../api/client";

// 使用標準 new URL() 模式設定 worker，相容性比 Vite 專屬的 `?url` 語法更穩定，
// 在某些 pdfjs-dist + Vite 版本組合下 `?url` 寫法會讓 Vite 在解析階段直接失敗，
// 導致整個開發伺服器無回應（畫面空白、console 無任何錯誤訊息）。
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url
).toString();

// 預設放大倍率：左右對分版面下，貼合容器寬度的 100% 往往字偏小，
// 預設拉高到 140% 讓多數情況下首次開啟就能看清楚文字，
// 使用者仍可用工具列按鈕自由調整 50%–300%。
const DEFAULT_ZOOM = 1.4;

/**
 * PdfViewer — 左側 PDF 預覽
 *
 * 職責：
 * 1. 用 pdf.js 把每一頁渲染到獨立的 <canvas>
 * 2. 在每個 canvas 上方疊一層透明 div，依 block.bbox 畫出可點擊區域
 * 3. activeBlockId 變動時自動捲動到對應頁面並高亮
 *
 * 座標換算重點：
 * - 後端 parser.py 使用 pdfplumber 的座標系，bbox = [x0, top, x1, bottom]，
 *   top/bottom 是「從頁面頂部算起」的距離，方向與螢幕座標系一致，
 *   不需要再做 Y 軸翻轉，只需乘上 viewport.scale 即為螢幕 px。
 *
 * Props:
 *   docId: string
 *   pageCount: number
 *   blocksByPage: { [page: number]: Array<{id, type, bbox}> }
 *   activeBlockId: string | null
 *   onBlockClick: (blockId: string) => void
 */
export default function PdfViewer({
  docId,
  pageCount,
  blocksByPage,
  activeBlockId,
  onBlockClick,
}) {
  const containerRef = useRef(null);
  const pageRefs = useRef({}); // { [pageNum]: HTMLDivElement }
  const [pdfDoc, setPdfDoc] = useState(null);
  const [pageViewports, setPageViewports] = useState({}); // { [pageNum]: {width, height, scale} }
  const [loadError, setLoadError] = useState(null);
  const [zoomFactor, setZoomFactor] = useState(DEFAULT_ZOOM);

  // ── 載入 PDF 文件 ──────────────────────────────────────────
  useEffect(() => {
    if (!docId) return;
    let cancelled = false;

    setLoadError(null);
    setPdfDoc(null);

    const loadingTask = pdfjsLib.getDocument(rawPdfUrl(docId));
    loadingTask.promise
      .then((doc) => {
        if (!cancelled) setPdfDoc(doc);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err.message || "PDF 載入失敗");
      });

    return () => {
      cancelled = true;
      loadingTask.destroy?.();
    };
  }, [docId]);

  // ── 逐頁渲染到 canvas ──────────────────────────────────────
  useEffect(() => {
    if (!pdfDoc) return;
    let cancelled = false;

    async function renderAllPages() {
      const viewports = {};

      for (let pageNum = 1; pageNum <= pdfDoc.numPages; pageNum++) {
        if (cancelled) return;

        const page = await pdfDoc.getPage(pageNum);
        const containerEl = pageRefs.current[pageNum];
        if (!containerEl) continue;

        // 依容器寬度自動計算基礎縮放比例，再乘上使用者調整的 zoomFactor
        const unscaledViewport = page.getViewport({ scale: 1 });
        const targetWidth = containerEl.clientWidth || 600;
        const baseScale = targetWidth / unscaledViewport.width;
        const scale = baseScale * zoomFactor;
        const viewport = page.getViewport({ scale });

        const canvas = containerEl.querySelector("canvas");
        if (!canvas) continue;

        canvas.width = viewport.width;
        canvas.height = viewport.height;
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;

        const ctx = canvas.getContext("2d");
        await page.render({ canvasContext: ctx, viewport }).promise;

        viewports[pageNum] = {
          width: viewport.width,
          height: viewport.height,
          scale,
        };
      }

      if (!cancelled) setPageViewports(viewports);
    }

    renderAllPages();
    return () => {
      cancelled = true;
    };
  }, [pdfDoc, zoomFactor]);

  // ── activeBlockId 變動時捲動到對應頁面 ─────────────────────
  useEffect(() => {
    if (!activeBlockId) return;
    for (const [pageNum, blocks] of Object.entries(blocksByPage)) {
      if (blocks.some((b) => b.id === activeBlockId)) {
        pageRefs.current[pageNum]?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
        break;
      }
    }
  }, [activeBlockId, blocksByPage]);

  const setPageRef = useCallback((pageNum, el) => {
    pageRefs.current[pageNum] = el;
  }, []);

  if (loadError) {
    return <div className="pdf-viewer-error">PDF 載入失敗：{loadError}</div>;
  }

  if (!pdfDoc) {
    return <div className="pdf-viewer-loading">PDF 載入中…</div>;
  }

  const pageNumbers = Array.from({ length: pdfDoc.numPages }, (_, i) => i + 1);

  const zoomIn = () => setZoomFactor((z) => Math.min(z + 0.25, 3));
  const zoomOut = () => setZoomFactor((z) => Math.max(z - 0.25, 0.5));
  const zoomReset = () => setZoomFactor(DEFAULT_ZOOM);

  return (
    <div className="pdf-viewer-wrapper">
      <div className="pdf-zoom-toolbar">
        <button type="button" onClick={zoomOut} aria-label="縮小" disabled={zoomFactor <= 0.5}>
          −
        </button>
        <span className="pdf-zoom-level">{Math.round(zoomFactor * 100)}%</span>
        <button type="button" onClick={zoomIn} aria-label="放大" disabled={zoomFactor >= 3}>
          ＋
        </button>
        {zoomFactor !== DEFAULT_ZOOM && (
          <button type="button" onClick={zoomReset} className="pdf-zoom-reset">
            重設
          </button>
        )}
      </div>
      <div className="pdf-viewer" ref={containerRef}>
        {pageNumbers.map((pageNum) => (
          <PdfPage
            key={pageNum}
            pageNum={pageNum}
            setRef={setPageRef}
            viewport={pageViewports[pageNum]}
            blocks={blocksByPage[pageNum] || []}
            activeBlockId={activeBlockId}
            onBlockClick={onBlockClick}
          />
        ))}
      </div>
    </div>
  );
}

/** 單頁容器：canvas + bbox 疊加層。 */
function PdfPage({ pageNum, setRef, viewport, blocks, activeBlockId, onBlockClick }) {
  return (
    <div
      className="pdf-page"
      ref={(el) => setRef(pageNum, el)}
      data-page={pageNum}
    >
      <canvas className="pdf-page-canvas" />
      {viewport && (
        <div className="pdf-page-overlay">
          {blocks.map((block) => (
            <BlockHighlight
              key={block.id}
              block={block}
              viewport={viewport}
              isActive={block.id === activeBlockId}
              onClick={() => onBlockClick(block.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * BlockHighlight — 依 bbox 換算成 px 座標的可點擊疊加區塊。
 *
 * bbox = [x0, top, x1, bottom]，單位是 PDF 原始座標（未縮放）。
 * 乘上 viewport.scale 即為螢幕 px。
 */
function BlockHighlight({ block, viewport, isActive, onClick }) {
  const [x0, top, x1, bottom] = block.bbox || [0, 0, 0, 0];
  const { scale } = viewport;

  const style = {
    left: `${x0 * scale}px`,
    top: `${top * scale}px`,
    width: `${Math.max((x1 - x0) * scale, 4)}px`,
    height: `${Math.max((bottom - top) * scale, 4)}px`,
  };

  return (
    <div
      className={`pdf-block-highlight pdf-block-${block.type}${
        isActive ? " pdf-block-active" : ""
      }`}
      style={style}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      title={block.type}
    />
  );
}

/**
 * 工具函式：將 useDocument 的 structure/texts/tables 轉成
 * PdfViewer 需要的 { [page]: [{id, type, bbox}] } 形狀。
 * 供 App.jsx 組裝 props 時使用。
 */
export function buildBlocksByPage(structure, texts, tables) {
  const result = {};
  for (const blockId of structure) {
    const block = texts[blockId] || tables[blockId];
    if (!block || !block.bbox) continue;
    const page = block.page || 1;
    if (!result[page]) result[page] = [];
    result[page].push({ id: blockId, type: block.type, bbox: block.bbox });
  }
  return result;
}
