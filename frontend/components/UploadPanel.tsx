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
        <div className="flex gap-1 rounded-full bg-neutral-100 p-1" role="tablist" aria-label="Input method">
          {(["upload", "paste"] as Mode[]).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={mode === m}
              onClick={() => setMode(m)}
              className={`rounded-full px-3.5 py-1 text-xs font-medium transition-all duration-300 ease-out ${
                mode === m ? "bg-black text-white" : "text-neutral-500 hover:text-black"
              }`}
            >
              {m === "upload" ? "Upload file" : "Paste diff"}
            </button>
          ))}
        </div>
      }
    >
      <div className="space-y-5">
        {mode === "upload" ? (
          <div key="upload" className="animate-fade-in space-y-4">
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
              className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border border-dashed px-6 py-12 text-center transition-all duration-300 ease-out ${
                dragging ? "scale-[1.005] border-black bg-neutral-100" : "border-black/25 hover:border-black hover:bg-neutral-50"
              }`}
            >
              <p className="text-sm font-medium text-black">
                Drag a unified diff here, or <span className="underline underline-offset-4">choose a file</span>
              </p>
              <p className="text-xs text-neutral-500">
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
              <div className="animate-fade-up flex flex-wrap items-center justify-between gap-2 rounded-xl border border-black/10 px-4 py-2.5 text-sm">
                <span className="truncate font-mono text-black">
                  {file.name} <span className="text-neutral-500">({(file.size / 1024).toFixed(1)} KB)</span>
                </span>
                <button
                  onClick={() => setFile(null)}
                  className="text-xs text-neutral-500 underline underline-offset-4 transition-colors hover:text-black"
                >
                  Remove
                </button>
              </div>
            )}
          </div>
        ) : (
          <div key="paste" className="animate-fade-in space-y-2">
            <label htmlFor="pasted-diff" className="text-xs font-medium text-neutral-600">
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
              className="w-full rounded-xl border border-black/15 bg-white p-4 font-mono text-xs text-black transition-all duration-200 placeholder:text-neutral-400 focus:border-black focus:outline-none focus:ring-4 focus:ring-black/5"
            />
            <p className="text-xs text-neutral-500">{pasted.length.toLocaleString()} characters</p>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={mode === "upload" ? handleFileSubmit : handlePasteSubmit}
            disabled={submitting || (mode === "upload" ? !file : !pasted.trim())}
            className="inline-flex items-center rounded-full bg-black px-5 py-2.5 text-sm font-medium text-white transition-all duration-200 hover:bg-neutral-800 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-30"
          >
            {submitting ? "Submitting…" : "Start review"}
          </button>
          <button
            onClick={loadSample}
            className="rounded-full border border-black/20 px-5 py-2.5 text-sm font-medium text-black transition-all duration-200 hover:border-black hover:bg-black hover:text-white active:scale-[0.97]"
          >
            Load sample demo diff
          </button>
          {usingSample && (
            <span className="animate-fade-in rounded-full border border-dashed border-black/40 px-2.5 py-0.5 text-xs text-neutral-600">
              {SAMPLE_DEMO_LABEL}
            </span>
          )}
        </div>

        {error && <Alert tone="error">{error}</Alert>}
      </div>
    </Card>
  );
}
