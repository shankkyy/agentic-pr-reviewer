"use client";

import { useRef, useState } from "react";
import { MAX_UPLOAD_BYTES, quickValidateDiff } from "@/lib/api";
import { SAMPLE_DEMO_DIFF, SAMPLE_DEMO_LABEL } from "@/lib/sampleDiff";
import { Alert, Card } from "./ui";

type Mode = "upload" | "paste";

interface Props {
  onSubmitPaste: (diffText: string, name: string) => Promise<void>;
  onSubmitFile: (file: File) => Promise<void>;
  submitting: boolean;
  submitError: string | null;
}

export default function UploadPanel({ onSubmitPaste, onSubmitFile, submitting, submitError }: Props) {
  const [mode, setMode] = useState<Mode>("upload");
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [pasted, setPasted] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [usingSample, setUsingSample] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function acceptFile(candidate: File | undefined) {
    setLocalError(null);
    setUsingSample(false);
    if (!candidate) return;
    if (candidate.size > MAX_UPLOAD_BYTES) {
      setFile(null);
      setLocalError(`"${candidate.name}" is ${(candidate.size / 1024).toFixed(0)} KB. The limit is 1 MB.`);
      return;
    }
    setFile(candidate);
  }

  async function handleFileSubmit() {
    if (!file) return;
    setLocalError(null);
    try {
      const text = await file.text();
      const problem = quickValidateDiff(text);
      if (problem) {
        setLocalError(problem);
        return;
      }
    } catch {
      setLocalError("The file could not be read as text.");
      return;
    }
    await onSubmitFile(file);
  }

  async function handlePasteSubmit() {
    setLocalError(null);
    const problem = quickValidateDiff(pasted);
    if (problem) {
      setLocalError(problem);
      return;
    }
    await onSubmitPaste(pasted, usingSample ? "sample-demo.diff" : "pasted-diff");
  }

  function loadSample() {
    setMode("paste");
    setPasted(SAMPLE_DEMO_DIFF);
    setUsingSample(true);
    setLocalError(null);
  }

  const error = localError ?? submitError;

  return (
    <Card
      title="New review"
      actions={
        <div className="flex gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800" role="tablist" aria-label="Input method">
          {(["upload", "paste"] as Mode[]).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={mode === m}
              onClick={() => setMode(m)}
              className={`rounded-md px-3 py-1 text-xs font-medium ${
                mode === m ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white" : "text-slate-600 dark:text-slate-300"
              }`}
            >
              {m === "upload" ? "Upload file" : "Paste diff"}
            </button>
          ))}
        </div>
      }
    >
      <div className="space-y-4">
        {mode === "upload" ? (
          <>
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                acceptFile(e.dataTransfer.files?.[0]);
              }}
              onClick={() => inputRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
              }}
              role="button"
              tabIndex={0}
              aria-label="Drop a diff file here or press Enter to choose one"
              className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
                dragging
                  ? "border-blue-500 bg-blue-50 dark:bg-blue-950/40"
                  : "border-slate-300 hover:border-slate-400 dark:border-slate-700 dark:hover:border-slate-600"
              }`}
            >
              <p className="text-sm font-medium text-slate-800 dark:text-slate-100">
                Drag a unified diff here, or <span className="text-blue-600 dark:text-blue-400">choose a file</span>
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                .diff or .patch, up to 1 MB. The server validates content; file extensions are not trusted.
              </p>
              <input
                ref={inputRef}
                type="file"
                className="hidden"
                onChange={(e) => acceptFile(e.target.files?.[0])}
                aria-label="Diff file"
              />
            </div>
            {file && (
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-2 text-sm dark:bg-slate-800">
                <span className="truncate font-mono text-slate-700 dark:text-slate-200">
                  {file.name} <span className="text-slate-500">({(file.size / 1024).toFixed(1)} KB)</span>
                </span>
                <button
                  onClick={() => setFile(null)}
                  className="text-xs text-slate-500 underline hover:text-slate-800 dark:hover:text-slate-200"
                >
                  Remove
                </button>
              </div>
            )}
          </>
        ) : (
          <div className="space-y-2">
            <label htmlFor="pasted-diff" className="text-xs font-medium text-slate-600 dark:text-slate-300">
              Unified diff text
            </label>
            <textarea
              id="pasted-diff"
              value={pasted}
              onChange={(e) => {
                setPasted(e.target.value);
                setUsingSample(false);
              }}
              spellCheck={false}
              rows={12}
              placeholder={"diff --git a/app/x.py b/app/x.py\n--- a/app/x.py\n+++ b/app/x.py\n@@ -1 +1 @@\n-old\n+new"}
              className="w-full rounded-lg border border-slate-300 bg-white p-3 font-mono text-xs text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:focus:ring-blue-900"
            />
            <p className="text-xs text-slate-500 dark:text-slate-400">{pasted.length.toLocaleString()} characters</p>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={mode === "upload" ? handleFileSubmit : handlePasteSubmit}
            disabled={submitting || (mode === "upload" ? !file : !pasted.trim())}
            className="inline-flex items-center rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? "Submitting…" : "Start review"}
          </button>
          <button
            onClick={loadSample}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            Load sample demo diff
          </button>
          {usingSample && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-950 dark:text-amber-200">
              {SAMPLE_DEMO_LABEL}
            </span>
          )}
        </div>

        {error && <Alert tone="error">{error}</Alert>}
      </div>
    </Card>
  );
}
