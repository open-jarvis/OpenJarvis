"""Native Serena document operator tools.

Serena Documents Full Operator v1 foundation:
- locate/index documents
- read/extract supported file types
- summarize and classify
- inspect quality/completeness
- save reports locally
- protect originals from overwrite
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from docx import Document as DocxDocument
except Exception:  # pragma: no cover
    DocxDocument = None

from openjarvis.tools._stubs import BaseTool, ToolResult, ToolSpec
from openjarvis.core.registry import ToolRegistry


SUPPORTED_TEXT_SUFFIXES = {".txt", ".md", ".rtf"}
SUPPORTED_DOC_SUFFIXES = {".docx"}
SUPPORTED_SUFFIXES = SUPPORTED_TEXT_SUFFIXES | SUPPORTED_DOC_SUFFIXES


def _documents_root() -> Path:
    root = Path("outputs/documents")
    root.mkdir(parents=True, exist_ok=True)
    for child in ["library", "reports", "extracted", "summaries", "snapshots"]:
        (root / child).mkdir(parents=True, exist_ok=True)
    return root


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "document"


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _resolve_path(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Document path not found: {p}")
    return p


def _read_text_like(path: Path) -> str:
    data = path.read_bytes()

    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue

    return data.decode("utf-8", errors="replace")


def _strip_rtf(text: str) -> str:
    # Lightweight RTF cleanup. Not a full RTF parser, but useful for many exported notes/docs.
    text = re.sub(r"{\\\*?\\[^{}]+}", " ", text)
    text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    return re.sub(r"\s+", " ", text).strip()


def _extract_docx(path: Path) -> str:
    if DocxDocument is None:
        raise RuntimeError("python-docx is not installed. Run: uv add python-docx")
    doc = DocxDocument(str(path))
    parts: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            parts.append(text)
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts).strip()


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return _read_text_like(path).strip()
    if suffix == ".rtf":
        return _strip_rtf(_read_text_like(path))
    if suffix == ".docx":
        return _extract_docx(path)
    raise RuntimeError(f"Unsupported document type for v1 extraction: {suffix}")


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _line_count(text: str) -> int:
    return len([line for line in text.splitlines() if line.strip()])


def _classify_document(path: Path, text: str) -> dict[str, Any]:
    lower = text.lower()
    name = path.name.lower()

    scores = {
        "clinical_or_health": sum(k in lower for k in ["patient", "diagnosis", "treatment", "clinical", "medical", "health", "symptom", "doctor"]),
        "financial_or_billing": sum(k in lower for k in ["invoice", "payment", "claim", "billing", "amount", "tax", "medical aid", "statement"]),
        "legal_or_compliance": sum(k in lower for k in ["agreement", "contract", "terms", "privacy", "compliance", "policy", "consent", "liability"]),
        "marketing_or_content": sum(k in lower for k in ["seo", "blog", "newsletter", "campaign", "content", "social media", "cta", "landing page"]),
        "technical_or_project": sum(k in lower for k in ["api", "code", "system", "architecture", "deployment", "github", "server", "workflow"]),
        "general_document": 1,
    }

    if "cv" in name or "curriculum" in lower:
        scores["cv_or_profile"] = 5

    doc_type = max(scores, key=scores.get)
    confidence = min(0.95, 0.35 + (scores[doc_type] * 0.12))

    sensitivity_flags = []
    if scores.get("clinical_or_health", 0) >= 2:
        sensitivity_flags.append("healthcare/clinical")
    if scores.get("financial_or_billing", 0) >= 2:
        sensitivity_flags.append("financial/billing")
    if scores.get("legal_or_compliance", 0) >= 2:
        sensitivity_flags.append("legal/compliance")

    return {
        "document_type": doc_type,
        "confidence": round(confidence, 2),
        "scores": scores,
        "sensitivity_flags": sensitivity_flags,
    }


def _summarize_text(text: str, max_sentences: int = 6) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return "No readable text extracted."

    sentences = re.split(r"(?<=[.!?])\s+", clean)
    selected = [s.strip() for s in sentences if s.strip()][:max_sentences]

    if not selected:
        return clean[:1200]

    summary = " ".join(selected)
    return summary[:1800]


def _inspect_document(path: Path, text: str) -> dict[str, Any]:
    words = _word_count(text)
    lines = _line_count(text)

    issues = []
    recommendations = []

    if not text.strip():
        issues.append("no_readable_text")
        recommendations.append("Use OCR or a different extraction path if this is scanned/image-based.")
    if words < 50:
        issues.append("very_short_text")
        recommendations.append("Confirm the document extracted correctly; it may be empty, scanned, or incomplete.")
    if words > 20000:
        recommendations.append("Large document detected. Consider section-based summaries.")
    if "signature" in text.lower() or "signed" in text.lower():
        recommendations.append("Signature-related language detected. Avoid altering original file.")
    if any(k in text.lower() for k in ["patient", "medical", "diagnosis", "treatment"]):
        recommendations.append("Healthcare content detected. Summarize and flag; do not make clinical decisions.")
    if any(k in text.lower() for k in ["contract", "agreement", "liability", "terms"]):
        recommendations.append("Legal/compliance language detected. Summarize and flag; do not provide final legal judgment.")

    return {
        "path": str(path),
        "filename": path.name,
        "suffix": path.suffix.lower(),
        "size_bytes": path.stat().st_size,
        "word_count": words,
        "line_count": lines,
        "issues": issues,
        "recommendations": recommendations,
    }


def _save_text_artifact(kind: str, source: Path, content: str, suffix: str = ".md") -> Path:
    root = _documents_root()
    out_dir = root / kind
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{_timestamp()}-{_safe_slug(source.stem)}{suffix}"
    path.write_text(content, encoding="utf-8")
    return path


class _DocumentsBaseTool(BaseTool):
    def _result(self, content: str, success: bool = True, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(
            tool_name=getattr(self, "tool_id", self.__class__.__name__),
            success=success,
            content=content,
            metadata=metadata or {},
        )


@ToolRegistry.register("serena_documents_status")
class SerenaDocumentsStatusTool(_DocumentsBaseTool):
    tool_id = "serena_documents_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show Serena Documents Full Operator v1 status and supported formats.",
            parameters={"type": "object", "properties": {}},
            category="serena_documents",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = _documents_root()
        return self._result(
            "Serena Documents status\n\n"
            "- Status: active\n"
            "- Supported v1 formats: .txt, .md, .rtf, .docx\n"
            "- PDF/OCR/Google Drive: planned next layers\n"
            f"- Output root: {root}\n"
            f"- Reports: {root / 'reports'}\n"
            f"- Extracted text: {root / 'extracted'}\n"
            f"- Summaries: {root / 'summaries'}\n"
            f"- Snapshots: {root / 'snapshots'}",
            metadata={"root": str(root), "supported_formats": sorted(SUPPORTED_SUFFIXES)},
        )


@ToolRegistry.register("serena_documents_index")
class SerenaDocumentsIndexTool(_DocumentsBaseTool):
    tool_id = "serena_documents_index"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Index supported local documents in a folder.",
            parameters={
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "description": "Folder to scan."},
                    "recursive": {"type": "boolean", "description": "Scan recursively."},
                    "limit": {"type": "integer", "description": "Maximum files to list."},
                },
                "required": ["folder"],
            },
            category="serena_documents",
        )

    def execute(self, **params: Any) -> ToolResult:
        folder = _resolve_path(str(params.get("folder") or ""))
        recursive = bool(params.get("recursive", True))
        limit = int(params.get("limit") or 100)

        if not folder.is_dir():
            return self._result(f"Not a folder: {folder}", success=False)

        pattern = "**/*" if recursive else "*"
        files = [
            p for p in folder.glob(pattern)
            if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
        ][:limit]

        lines = [
            "Serena document index",
            "",
            f"- Folder: {folder}",
            f"- Recursive: {'yes' if recursive else 'no'}",
            f"- Supported documents found: {len(files)}",
            "",
            "Documents:",
        ]

        if not files:
            lines.append("- none")
        else:
            for p in files:
                lines.append(f"- {p.name} | {p.suffix.lower()} | {p.stat().st_size} bytes | {p}")

        index_path = _save_text_artifact("reports", folder, "\n".join(lines), suffix=".md")

        return self._result(
            "\n".join(lines) + f"\n\nIndex saved: {index_path}",
            metadata={"folder": str(folder), "count": len(files), "index_path": str(index_path)},
        )


@ToolRegistry.register("serena_documents_extract")
class SerenaDocumentsExtractTool(_DocumentsBaseTool):
    tool_id = "serena_documents_extract"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Extract readable text from a supported local document and save it.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Document path."}
                },
                "required": ["path"],
            },
            category="serena_documents",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            path = _resolve_path(str(params.get("path") or ""))
            text = _extract_text(path)
            out_path = _save_text_artifact("extracted", path, text, suffix=".txt")
            inspection = _inspect_document(path, text)

            return self._result(
                "Serena document text extracted\n\n"
                f"- Source: {path}\n"
                f"- Output: {out_path}\n"
                f"- Word count: {inspection['word_count']}\n"
                f"- Line count: {inspection['line_count']}",
                metadata={"source": str(path), "output": str(out_path), **inspection},
            )
        except Exception as exc:
            return self._result(f"Failed to extract document text: {exc}", success=False)


@ToolRegistry.register("serena_documents_read")
class SerenaDocumentsReadTool(SerenaDocumentsExtractTool):
    tool_id = "serena_documents_read"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Read/extract a supported local document.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Document path."},
                    "preview_chars": {"type": "integer", "description": "Preview character count."},
                },
                "required": ["path"],
            },
            category="serena_documents",
        )

    def execute(self, **params: Any) -> ToolResult:
        result = super().execute(**params)
        if not result.success:
            return result

        output = Path(result.metadata["output"])
        text = output.read_text(encoding="utf-8")
        preview_chars = int(params.get("preview_chars") or 2000)
        preview = text[:preview_chars]

        return self._result(
            result.content + "\n\nPreview:\n" + preview,
            metadata={**result.metadata, "preview_chars": preview_chars},
        )


@ToolRegistry.register("serena_documents_summarize")
class SerenaDocumentsSummarizeTool(_DocumentsBaseTool):
    tool_id = "serena_documents_summarize"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Extract and summarize a supported local document.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Document path."},
                    "max_sentences": {"type": "integer", "description": "Maximum summary sentences."},
                },
                "required": ["path"],
            },
            category="serena_documents",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            path = _resolve_path(str(params.get("path") or ""))
            text = _extract_text(path)
            summary = _summarize_text(text, max_sentences=int(params.get("max_sentences") or 6))
            classification = _classify_document(path, text)
            inspection = _inspect_document(path, text)

            report = (
                f"# Document Summary\n\n"
                f"Source: `{path}`\n\n"
                f"## Summary\n\n{summary}\n\n"
                f"## Classification\n\n"
                f"- Type: {classification['document_type']}\n"
                f"- Confidence: {classification['confidence']}\n"
                f"- Sensitivity flags: {', '.join(classification['sensitivity_flags']) or 'none'}\n\n"
                f"## Inspection\n\n"
                f"- Word count: {inspection['word_count']}\n"
                f"- Line count: {inspection['line_count']}\n"
                f"- Issues: {', '.join(inspection['issues']) or 'none'}\n"
            )

            out_path = _save_text_artifact("summaries", path, report, suffix=".md")

            return self._result(
                "Serena document summary created\n\n"
                f"- Source: {path}\n"
                f"- Summary: {out_path}\n"
                f"- Type: {classification['document_type']}\n"
                f"- Sensitivity flags: {', '.join(classification['sensitivity_flags']) or 'none'}\n\n"
                f"Summary preview:\n{summary}",
                metadata={"source": str(path), "summary_path": str(out_path), **classification, **inspection},
            )
        except Exception as exc:
            return self._result(f"Failed to summarize document: {exc}", success=False)


@ToolRegistry.register("serena_documents_classify")
class SerenaDocumentsClassifyTool(_DocumentsBaseTool):
    tool_id = "serena_documents_classify"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Classify a supported local document and flag sensitivity.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Document path."}
                },
                "required": ["path"],
            },
            category="serena_documents",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            path = _resolve_path(str(params.get("path") or ""))
            text = _extract_text(path)
            classification = _classify_document(path, text)
            inspection = _inspect_document(path, text)

            return self._result(
                "Serena document classification\n\n"
                f"- Source: {path}\n"
                f"- Type: {classification['document_type']}\n"
                f"- Confidence: {classification['confidence']}\n"
                f"- Sensitivity flags: {', '.join(classification['sensitivity_flags']) or 'none'}\n"
                f"- Word count: {inspection['word_count']}",
                metadata={"source": str(path), **classification, **inspection},
            )
        except Exception as exc:
            return self._result(f"Failed to classify document: {exc}", success=False)


@ToolRegistry.register("serena_documents_inspect")
class SerenaDocumentsInspectTool(_DocumentsBaseTool):
    tool_id = "serena_documents_inspect"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Inspect a supported local document for extraction quality, completeness, and safety flags.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Document path."}
                },
                "required": ["path"],
            },
            category="serena_documents",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            path = _resolve_path(str(params.get("path") or ""))
            text = _extract_text(path)
            inspection = _inspect_document(path, text)
            classification = _classify_document(path, text)

            lines = [
                "Serena document inspection",
                "",
                f"- Source: {path}",
                f"- File type: {inspection['suffix']}",
                f"- Size: {inspection['size_bytes']} bytes",
                f"- Word count: {inspection['word_count']}",
                f"- Line count: {inspection['line_count']}",
                f"- Classified as: {classification['document_type']} ({classification['confidence']})",
                f"- Sensitivity flags: {', '.join(classification['sensitivity_flags']) or 'none'}",
                "",
                "Issues:",
            ]

            lines.extend(f"- {issue}" for issue in inspection["issues"] or ["none"])
            lines.append("")
            lines.append("Recommendations:")
            lines.extend(f"- {rec}" for rec in inspection["recommendations"] or ["No major recommendations."])

            return self._result("\n".join(lines), metadata={**inspection, **classification})
        except Exception as exc:
            return self._result(f"Failed to inspect document: {exc}", success=False)


@ToolRegistry.register("serena_documents_report")
class SerenaDocumentsReportTool(_DocumentsBaseTool):
    tool_id = "serena_documents_report"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a complete Serena document operator report for a supported local document.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Document path."}
                },
                "required": ["path"],
            },
            category="serena_documents",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            path = _resolve_path(str(params.get("path") or ""))
            text = _extract_text(path)
            classification = _classify_document(path, text)
            inspection = _inspect_document(path, text)
            summary = _summarize_text(text, max_sentences=8)

            report = f"""# Serena Document Operator Report

Source: `{path}`

## Identity

- Filename: {path.name}
- Type: {path.suffix.lower()}
- Size: {path.stat().st_size} bytes

## Classification

- Document type: {classification['document_type']}
- Confidence: {classification['confidence']}
- Sensitivity flags: {', '.join(classification['sensitivity_flags']) or 'none'}

## Extraction Quality

- Word count: {inspection['word_count']}
- Line count: {inspection['line_count']}
- Issues: {', '.join(inspection['issues']) or 'none'}

## Summary

{summary}

## Recommendations

{chr(10).join('- ' + rec for rec in inspection['recommendations']) if inspection['recommendations'] else '- No major recommendations.'}

## Operator Notes

- Original file was not modified.
- Generated outputs are stored under `outputs/documents/`.
- For healthcare/legal/financial documents, Serena provides summaries and flags, not final professional decisions.
"""

            out_path = _save_text_artifact("reports", path, report, suffix=".md")

            return self._result(
                "Serena document operator report created\n\n"
                f"- Source: {path}\n"
                f"- Report: {out_path}\n"
                f"- Type: {classification['document_type']}\n"
                f"- Word count: {inspection['word_count']}",
                metadata={"source": str(path), "report_path": str(out_path), **classification, **inspection},
            )
        except Exception as exc:
            return self._result(f"Failed to create document report: {exc}", success=False)


def _library_dir(category: str = "general") -> Path:
    root = _documents_root() / "library" / _safe_slug(category)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _snapshot_document(path: Path, reason: str) -> Path:
    root = _documents_root() / "snapshots"
    root.mkdir(parents=True, exist_ok=True)

    timestamp = _timestamp()
    target = root / f"{timestamp}-{_safe_slug(path.stem)}-{_safe_slug(reason)}{path.suffix.lower()}"

    if path.exists() and path.is_file():
        shutil.copy2(path, target)

    meta = {
        "source": str(path),
        "snapshot": str(target),
        "reason": reason,
        "timestamp": timestamp,
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }

    meta_path = target.with_suffix(target.suffix + ".json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return target


@ToolRegistry.register("serena_documents_import")
class SerenaDocumentsImportTool(_DocumentsBaseTool):
    tool_id = "serena_documents_import"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Copy a document into Serena's controlled document library without modifying the original.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Source document path."},
                    "category": {"type": "string", "description": "Library category/folder."},
                },
                "required": ["path"],
            },
            category="serena_documents",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            source = _resolve_path(str(params.get("path") or ""))
            category = str(params.get("category") or "general").strip() or "general"

            if not source.is_file():
                return self._result(f"Not a file: {source}", success=False)

            if source.suffix.lower() not in SUPPORTED_SUFFIXES:
                return self._result(
                    f"Unsupported v1 document type: {source.suffix.lower()}",
                    success=False,
                    metadata={"supported": sorted(SUPPORTED_SUFFIXES)},
                )

            library = _library_dir(category)
            target = library / f"{_timestamp()}-{_safe_slug(source.stem)}{source.suffix.lower()}"

            shutil.copy2(source, target)

            text = _extract_text(target)
            classification = _classify_document(target, text)
            inspection = _inspect_document(target, text)

            meta = {
                "source": str(source),
                "library_path": str(target),
                "category": category,
                "imported_at": _timestamp(),
                "classification": classification,
                "inspection": inspection,
                "original_preserved": True,
            }

            meta_path = target.with_suffix(target.suffix + ".json")
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

            return self._result(
                "Serena document imported into controlled library\n\n"
                f"- Source: {source}\n"
                f"- Library path: {target}\n"
                f"- Metadata: {meta_path}\n"
                f"- Category: {category}\n"
                f"- Type: {classification['document_type']}\n"
                f"- Sensitivity flags: {', '.join(classification['sensitivity_flags']) or 'none'}\n"
                f"- Original preserved: yes",
                metadata={
                    "source": str(source),
                    "library_path": str(target),
                    "metadata_path": str(meta_path),
                    "category": category,
                    **classification,
                    **inspection,
                },
            )
        except Exception as exc:
            return self._result(f"Failed to import document: {exc}", success=False)


@ToolRegistry.register("serena_documents_library")
class SerenaDocumentsLibraryTool(_DocumentsBaseTool):
    tool_id = "serena_documents_library"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List Serena's controlled document library.",
            parameters={
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Optional category/folder."},
                    "limit": {"type": "integer", "description": "Maximum files to show."},
                },
            },
            category="serena_documents",
        )

    def execute(self, **params: Any) -> ToolResult:
        category = str(params.get("category") or "").strip()
        limit = int(params.get("limit") or 50)

        root = _documents_root() / "library"
        folder = _library_dir(category) if category else root

        files = [
            p for p in folder.glob("**/*")
            if p.is_file()
            and p.suffix.lower() in SUPPORTED_SUFFIXES
        ]

        files = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]

        lines = [
            "Serena document library",
            "",
            f"- Folder: {folder}",
            f"- Documents found: {len(files)}",
            "",
            "Documents:",
        ]

        if not files:
            lines.append("- none")
        else:
            for file in files:
                lines.append(f"- {file.name} | {file.suffix.lower()} | {file.stat().st_size} bytes | {file}")

        return self._result(
            "\n".join(lines),
            metadata={"folder": str(folder), "count": len(files)},
        )


@ToolRegistry.register("serena_documents_snapshot")
class SerenaDocumentsSnapshotTool(_DocumentsBaseTool):
    tool_id = "serena_documents_snapshot"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local safety snapshot of a document before any risky operation.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Document path."},
                    "reason": {"type": "string", "description": "Snapshot reason."},
                },
                "required": ["path"],
            },
            category="serena_documents",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            source = _resolve_path(str(params.get("path") or ""))
            reason = str(params.get("reason") or "manual-snapshot").strip() or "manual-snapshot"

            if not source.is_file():
                return self._result(f"Not a file: {source}", success=False)

            snapshot = _snapshot_document(source, reason)

            return self._result(
                "Serena document snapshot created\n\n"
                f"- Source: {source}\n"
                f"- Snapshot: {snapshot}\n"
                f"- Reason: {reason}",
                metadata={"source": str(source), "snapshot": str(snapshot), "reason": reason},
            )
        except Exception as exc:
            return self._result(f"Failed to snapshot document: {exc}", success=False)


@ToolRegistry.register("serena_documents_snapshots")
class SerenaDocumentsSnapshotsTool(_DocumentsBaseTool):
    tool_id = "serena_documents_snapshots"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List Serena document snapshots.",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Maximum snapshots to show."},
                },
            },
            category="serena_documents",
        )

    def execute(self, **params: Any) -> ToolResult:
        limit = int(params.get("limit") or 50)
        folder = _documents_root() / "snapshots"

        files = [
            p for p in folder.glob("*")
            if p.is_file()
            and not p.name.endswith(".json")
        ]

        files = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]

        lines = [
            "Serena document snapshots",
            "",
            f"- Folder: {folder}",
            f"- Snapshots found: {len(files)}",
            "",
            "Snapshots:",
        ]

        if not files:
            lines.append("- none")
        else:
            for file in files:
                lines.append(f"- {file.name} | {file.stat().st_size} bytes | {file}")

        return self._result(
            "\n".join(lines),
            metadata={"folder": str(folder), "count": len(files)},
        )


@ToolRegistry.register("serena_documents_audit")
class SerenaDocumentsAuditTool(_DocumentsBaseTool):
    tool_id = "serena_documents_audit"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Run Serena's document library audit dashboard.",
            parameters={
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "description": "Optional folder to audit. Defaults to outputs/documents/library."},
                    "recursive": {"type": "boolean", "description": "Scan recursively."},
                    "limit": {"type": "integer", "description": "Maximum files to audit."},
                },
            },
            category="serena_documents",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            root = _documents_root()
            folder_value = str(params.get("folder") or "").strip()
            folder = Path(folder_value) if folder_value else root / "library"
            recursive = bool(params.get("recursive", True))
            limit = int(params.get("limit") or 200)

            if not folder.exists() or not folder.is_dir():
                return self._result(f"Audit folder not found or not a folder: {folder}", success=False)

            pattern = "**/*" if recursive else "*"
            all_files = [p for p in folder.glob(pattern) if p.is_file()]
            document_files = [p for p in all_files if p.suffix.lower() in SUPPORTED_SUFFIXES][:limit]
            unsupported_files = [
                p for p in all_files
                if not p.name.endswith(".json")
                and p.suffix.lower() not in SUPPORTED_SUFFIXES
            ][:limit]

            audited: list[dict[str, Any]] = []
            extraction_failures: list[dict[str, str]] = []

            for doc_path in document_files:
                try:
                    text = _extract_text(doc_path)
                    classification = _classify_document(doc_path, text)
                    inspection = _inspect_document(doc_path, text)
                    meta_path = doc_path.with_suffix(doc_path.suffix + ".json")
                    audited.append(
                        {
                            "path": str(doc_path),
                            "name": doc_path.name,
                            "category": str(doc_path.parent.relative_to(root / "library")) if (root / "library") in doc_path.parents else "external",
                            "type": classification["document_type"],
                            "confidence": classification["confidence"],
                            "sensitivity_flags": classification["sensitivity_flags"],
                            "word_count": inspection["word_count"],
                            "line_count": inspection["line_count"],
                            "issues": inspection["issues"],
                            "recommendations": inspection["recommendations"],
                            "metadata_exists": meta_path.exists(),
                        }
                    )
                except Exception as exc:
                    extraction_failures.append({"path": str(doc_path), "error": str(exc)})

            sensitive = [x for x in audited if x["sensitivity_flags"]]
            short_or_empty = [x for x in audited if x["word_count"] < 50]
            missing_metadata = [x for x in audited if not x["metadata_exists"]]

            categories: dict[str, int] = {}
            doc_types: dict[str, int] = {}
            for item in audited:
                categories[item["category"]] = categories.get(item["category"], 0) + 1
                doc_types[item["type"]] = doc_types.get(item["type"], 0) + 1

            recent_reports = sorted((root / "reports").glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]
            recent_summaries = sorted((root / "summaries").glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]
            recent_snapshots = sorted(
                [p for p in (root / "snapshots").glob("*") if p.is_file() and not p.name.endswith(".json")],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:10]

            lines = [
                "Serena Documents audit dashboard",
                "",
                f"- Audit folder: {folder}",
                f"- Recursive: {'yes' if recursive else 'no'}",
                f"- Supported documents scanned: {len(audited)}",
                f"- Unsupported files found: {len(unsupported_files)}",
                f"- Extraction failures: {len(extraction_failures)}",
                "",
                "Summary:",
                f"- Sensitive documents flagged: {len(sensitive)}",
                f"- Very short/empty documents: {len(short_or_empty)}",
                f"- Documents missing metadata: {len(missing_metadata)}",
                f"- Recent reports: {len(recent_reports)}",
                f"- Recent summaries: {len(recent_summaries)}",
                f"- Recent snapshots: {len(recent_snapshots)}",
                "",
                "Documents by category:",
            ]

            if categories:
                for category, count in sorted(categories.items()):
                    lines.append(f"- {category}: {count}")
            else:
                lines.append("- none")

            lines.extend(["", "Documents by type:"])
            if doc_types:
                for doc_type, count in sorted(doc_types.items()):
                    lines.append(f"- {doc_type}: {count}")
            else:
                lines.append("- none")

            lines.extend(["", "Sensitive documents:"])
            if sensitive:
                for item in sensitive[:15]:
                    lines.append(
                        f"- {item['name']} | {item['type']} | flags: {', '.join(item['sensitivity_flags'])} | words {item['word_count']}"
                    )
            else:
                lines.append("- none")

            lines.extend(["", "Very short or empty documents:"])
            if short_or_empty:
                for item in short_or_empty[:15]:
                    lines.append(f"- {item['name']} | words {item['word_count']} | issues: {', '.join(item['issues']) or 'none'}")
            else:
                lines.append("- none")

            lines.extend(["", "Documents missing metadata:"])
            if missing_metadata:
                for item in missing_metadata[:15]:
                    lines.append(f"- {item['name']} | {item['path']}")
            else:
                lines.append("- none")

            lines.extend(["", "Unsupported files:"])
            if unsupported_files:
                for item in unsupported_files[:15]:
                    lines.append(f"- {item.name} | {item.suffix.lower()} | {item}")
            else:
                lines.append("- none")

            lines.extend(["", "Extraction failures:"])
            if extraction_failures:
                for item in extraction_failures[:15]:
                    lines.append(f"- {item['path']}: {item['error']}")
            else:
                lines.append("- none")

            lines.extend(["", "Recent reports:"])
            lines.extend(f"- {p.name}" for p in recent_reports) if recent_reports else lines.append("- none")

            lines.extend(["", "Recent summaries:"])
            lines.extend(f"- {p.name}" for p in recent_summaries) if recent_summaries else lines.append("- none")

            lines.extend(["", "Recent snapshots:"])
            lines.extend(f"- {p.name}" for p in recent_snapshots) if recent_snapshots else lines.append("- none")

            lines.extend([
                "",
                "Recommended operator actions:",
                "- Add metadata by importing unmanaged supported documents into Serena's document library.",
                "- Review sensitive documents carefully; summarize and flag, but do not make clinical/legal/financial decisions.",
                "- Use OCR/PDF layer later for scanned or unsupported documents.",
                "- Create snapshots before any move, rename, or cleanup action.",
                "- Generate reports for important documents before acting on them.",
            ])

            audit_report = _save_text_artifact("reports", folder, "\n".join(lines), suffix=".md")

            return self._result(
                "\n".join(lines) + f"\n\nAudit report saved: {audit_report}",
                metadata={
                    "folder": str(folder),
                    "documents_scanned": len(audited),
                    "unsupported_files": len(unsupported_files),
                    "extraction_failures": len(extraction_failures),
                    "sensitive_documents": len(sensitive),
                    "short_or_empty": len(short_or_empty),
                    "missing_metadata": len(missing_metadata),
                    "audit_report": str(audit_report),
                },
            )
        except Exception as exc:
            return self._result(f"Failed to run document audit: {exc}", success=False)


__all__ = [
    "SerenaDocumentsStatusTool",
    "SerenaDocumentsIndexTool",
    "SerenaDocumentsReadTool",
    "SerenaDocumentsExtractTool",
    "SerenaDocumentsSummarizeTool",
    "SerenaDocumentsClassifyTool",
    "SerenaDocumentsInspectTool",
    "SerenaDocumentsReportTool",
    "SerenaDocumentsSnapshotsTool",
    "SerenaDocumentsAuditTool",
    "SerenaDocumentsSnapshotTool",
    "SerenaDocumentsLibraryTool",
    "SerenaDocumentsImportTool",
]
