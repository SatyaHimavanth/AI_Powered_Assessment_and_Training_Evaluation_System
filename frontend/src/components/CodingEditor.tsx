import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import type { ReactCodeMirrorRef } from "@uiw/react-codemirror";
import { python } from "@codemirror/lang-python";
import { oneDark } from "@codemirror/theme-one-dark";
import { EditorView, Decoration } from "@codemirror/view";
import type { DecorationSet } from "@codemirror/view";
import { StateField, RangeSetBuilder, EditorState } from "@codemirror/state";
import api from "../api";

interface TestCase {
  id: string;
  input_data: string;
  expected_output: string;
}

interface TestCaseResult {
  test_case_id: string;
  passed: boolean;
  input_data: string;
  expected_output: string;
  actual_output: string;
  error: string | null;
}

interface Props {
  questionId: string;
  questionText: string;
  difficulty: string;
  sectionName: string;
  testCases: TestCase[];
  defaultCode: string;
  value: string;
  onChange: (code: string) => void;
  disablePaste?: boolean;
  onPasteAttempt?: () => void;
}

const EDITABLE_START = "# --- EDITABLE START ---";
const EDITABLE_END = "# --- EDITABLE END ---";

/** Parse default_code into header, editable placeholder, and footer */
function parseTemplate(defaultCode: string) {
  const startIdx = defaultCode.indexOf(EDITABLE_START);
  const endIdx = defaultCode.indexOf(EDITABLE_END);

  if (startIdx === -1 || endIdx === -1) {
    // No markers — entire code is editable
    return { header: "", editablePlaceholder: defaultCode, footer: "", hasTemplate: false };
  }

  const header = defaultCode.substring(0, startIdx + EDITABLE_START.length);
  const footer = defaultCode.substring(endIdx);
  const editablePlaceholder = defaultCode.substring(startIdx + EDITABLE_START.length + 1, endIdx); // +1 for newline

  return { header, editablePlaceholder, footer, hasTemplate: true };
}

/** Assemble full code from parts */
function assembleCode(header: string, editableContent: string, footer: string) {
  return header + "\n" + editableContent + "\n" + footer;
}

// Decoration for locked lines (dimmed appearance)
const lockedLineDecoration = Decoration.line({ class: "cm-locked-line" });

// Theme for locked lines
const lockedLineTheme = EditorView.baseTheme({
  ".cm-locked-line": {
    backgroundColor: "rgba(50, 50, 60, 0.5)",
    opacity: "0.7",
  },
  ".cm-locked-line *": {
    cursor: "not-allowed !important",
  },
});

export default function CodingEditor({
  questionId,
  questionText,
  difficulty,
  sectionName,
  testCases,
  defaultCode,
  value,
  onChange,
  disablePaste,
  onPasteAttempt,
}: Props) {
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<TestCaseResult[] | null>(null);
  const [activeTab, setActiveTab] = useState<"testcases" | "results">("testcases");
  const dividerRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [leftWidth, setLeftWidth] = useState(40);
  const editorRef = useRef<ReactCodeMirrorRef>(null);

  // When the parent switches to a different question, clear any previous run results
  // and reset the active tab so results from the prior question don't persist.
  useEffect(() => {
    setResults(null);
    setActiveTab("testcases");
    setRunning(false);
  }, [questionId]);

  // Parse the template
  const { header, editablePlaceholder, footer, hasTemplate } = useMemo(
    () => parseTemplate(defaultCode),
    [defaultCode]
  );

  // Compute line boundaries for locked regions
  const headerLineCount = useMemo(() => header ? header.split("\n").length : 0, [header]);
  const footerLineCount = useMemo(() => footer ? footer.split("\n").length : 0, [footer]);

  // The full code displayed in editor
  const fullCode = useMemo(() => {
    if (!hasTemplate) {
      return value || editablePlaceholder;
    }
    const editableContent = value || editablePlaceholder;
    return assembleCode(header, editableContent, footer);
  }, [hasTemplate, header, footer, value, editablePlaceholder]);

  // Detect language: SQL if defaultCode starts with SQL comment marker
  const language = (defaultCode || "").trim().startsWith("--") ? "sql" : "python";

  // Extract editable content from full editor text
  const extractEditable = useCallback((fullText: string) => {
    if (!hasTemplate) return fullText;
    const lines = fullText.split("\n");
    // Editable content is between headerLineCount and (total - footerLineCount)
    const editableLines = lines.slice(headerLineCount, lines.length - footerLineCount);
    return editableLines.join("\n");
  }, [hasTemplate, headerLineCount, footerLineCount]);

  // Handle editor changes - extract only editable portion
  const handleChange = useCallback((newFullCode: string) => {
    const editable = extractEditable(newFullCode);
    onChange(editable);
  }, [extractEditable, onChange]);

  // CodeMirror extensions for locked line decorations + edit filtering
  const readOnlyRanges = useMemo(() => {
    if (!hasTemplate) return [];

    return [
      lockedLineTheme,
      StateField.define<DecorationSet>({
        create(state) {
          const builder = new RangeSetBuilder<Decoration>();
          const doc = state.doc;
          for (let i = 1; i <= Math.min(headerLineCount, doc.lines); i++) {
            const line = doc.line(i);
            builder.add(line.from, line.from, lockedLineDecoration);
          }
          const footerStart = doc.lines - footerLineCount + 1;
          for (let i = Math.max(footerStart, 1); i <= doc.lines; i++) {
            const line = doc.line(i);
            builder.add(line.from, line.from, lockedLineDecoration);
          }
          return builder.finish();
        },
        update(decorations, tr) {
          if (!tr.docChanged) return decorations;
          const builder = new RangeSetBuilder<Decoration>();
          const doc = tr.state.doc;
          for (let i = 1; i <= Math.min(headerLineCount, doc.lines); i++) {
            const line = doc.line(i);
            builder.add(line.from, line.from, lockedLineDecoration);
          }
          const footerStart = doc.lines - footerLineCount + 1;
          for (let i = Math.max(footerStart, 1); i <= doc.lines; i++) {
            const line = doc.line(i);
            builder.add(line.from, line.from, lockedLineDecoration);
          }
          return builder.finish();
        },
        provide: (f) => EditorView.decorations.from(f),
      }),
      // Transaction filter: reject edits that touch locked regions
      EditorState.transactionFilter.of((tr) => {
        if (!tr.docChanged) return tr;
        const doc = tr.startState.doc;
        // Calculate locked character ranges
        const headerEnd = headerLineCount > 0 ? doc.line(Math.min(headerLineCount, doc.lines)).to : 0;
        const footerStartLine = doc.lines - footerLineCount + 1;
        const footerFrom = footerStartLine > 0 && footerStartLine <= doc.lines
          ? doc.line(footerStartLine).from
          : doc.length;

        let dominated = false;
        tr.changes.iterChanges((fromA, toA) => {
          // If change touches header or footer region, block it
          if (fromA < headerEnd || toA > footerFrom) {
            dominated = true;
          }
        });
        return dominated ? [] : tr;
      }),
    ];
  }, [hasTemplate, headerLineCount, footerLineCount]);

  // Build final extensions array and optionally attach DOM event handlers
  const cmExtensions = useMemo(() => {
    const exts: any[] = [...(language === "python" ? [python()] : []), ...readOnlyRanges];
    if (disablePaste) {
      exts.push(
        EditorView.domEventHandlers({
          paste: (e: any) => {
            e.preventDefault();
            try { onPasteAttempt?.(); } catch {}
            return true;
          },
          copy: (e: any) => {
            e.preventDefault();
            try { if (e.clipboardData && typeof e.clipboardData.setData === 'function') e.clipboardData.setData('text/plain', ''); } catch {}
            return true;
          },
          cut: (e: any) => {
            e.preventDefault();
            try { if (e.clipboardData && typeof e.clipboardData.setData === 'function') e.clipboardData.setData('text/plain', ''); } catch {}
            try { onPasteAttempt?.(); } catch {}
            return true;
          }
        })
      );
    }
    return exts;
  }, [language, readOnlyRanges, disablePaste, onPasteAttempt]);

  // Resizable divider
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = leftWidth;

    const onMouseMove = (ev: MouseEvent) => {
      if (!containerRef.current) return;
      const containerWidth = containerRef.current.getBoundingClientRect().width;
      const delta = ev.clientX - startX;
      const newPercent = startWidth + (delta / containerWidth) * 100;
      setLeftWidth(Math.max(20, Math.min(70, newPercent)));
    };

    const onMouseUp = () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  }, [leftWidth]);

  const runCode = async () => {
    setRunning(true);
    setActiveTab("results");
    try {
      // Send the FULL assembled code for execution
      const codeToRun = hasTemplate
        ? assembleCode(header, value || editablePlaceholder, footer)
        : value;
      const res = await api.post("/code/run", {
        question_id: questionId,
        code: codeToRun,
        run_sample_only: true,
        language: language,
      });
      setResults(res.data.results);
    } catch (err: unknown) {
      console.error(err);
      setResults([{
        test_case_id: "error",
        passed: false,
        input_data: "",
        expected_output: "",
        actual_output: "Execution failed",
        error: "Execution failed",
      }]);
    } finally {
      setRunning(false);
    }
  };

  const passedCount = results?.filter((r) => r.passed).length ?? 0;
  const totalCount = results?.length ?? 0;

  return (
    <div ref={containerRef} className="flex h-full w-full overflow-hidden min-h-0">
      {/* Left Panel - Question */}
      <div style={{ width: `${leftWidth}%` }} className="flex flex-col overflow-hidden bg-gray-800 min-h-0">
        <div className="p-5 overflow-y-auto flex-1 min-h-0">
          {/* Header */}
          <div className="flex items-center gap-2 mb-4">
            <span className="text-xs font-medium px-2 py-0.5 rounded bg-blue-900/40 text-blue-200">
              {sectionName}
            </span>
            <span className="text-xs font-medium px-2 py-0.5 rounded bg-purple-900/40 text-purple-200">
              CODING
            </span>
            <span className={`text-xs font-medium px-2 py-0.5 rounded ${
              difficulty === "easy" ? "bg-green-900 text-green-300" :
              difficulty === "medium" ? "bg-amber-900 text-amber-300" :
              "bg-red-900 text-red-300"
            }`}>
              {difficulty}
            </span>
          </div>

          {/* Question */}
          <div className="text-sm text-gray-200 leading-relaxed whitespace-pre-wrap mb-6">
            {questionText}
          </div>

          {/* Sample Test Cases */}
          {testCases.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
                Sample Test Cases
              </h3>
              <div className="space-y-3">
                {testCases.map((tc, idx) => (
                  <div key={tc.id} className="border border-gray-700 rounded-lg overflow-hidden">
                    <div className="px-3 py-1.5 bg-gray-700/50 text-xs font-medium text-gray-300">
                      Example {idx + 1}
                    </div>
                    <div className="p-3 space-y-2">
                      <div>
                        <span className="text-xs text-gray-500">Input:</span>
                        <pre className="text-xs text-gray-300 bg-gray-900 rounded px-2 py-1 mt-0.5 overflow-x-auto">
                          {tc.input_data || "(no input)"}
                        </pre>
                      </div>
                      <div>
                        <span className="text-xs text-gray-500">Expected Output:</span>
                        <pre className="text-xs text-gray-300 bg-gray-900 rounded px-2 py-1 mt-0.5 overflow-x-auto">
                          {tc.expected_output}
                        </pre>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Resizable Divider */}
      <div
        ref={dividerRef}
        onMouseDown={handleMouseDown}
        className="w-1.5 bg-gray-700 hover:bg-blue-500 cursor-col-resize flex-shrink-0 transition-colors"
      />

      {/* Right Panel - Code Editor + Results */}
      <div style={{ width: `${100 - leftWidth}%` }} className="flex flex-col overflow-hidden min-h-0">
        {/* Toolbar */}
        <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700">
          <div className="flex items-center gap-3">
            <select
              className="h-8 px-2 text-xs bg-gray-700 border border-gray-600 rounded text-gray-200 focus:outline-none"
              value={language === "sql" ? "sql" : "python"}
              disabled
            >
              {language === "sql" ? <option value="sql">SQL (Postgres)</option> : <option value="python">Python 3.12</option>}
            </select>
          </div>
          <button
            onClick={runCode}
            disabled={running || (!value.trim() && !hasTemplate)}
            className="h-8 px-4 text-xs font-medium rounded bg-green-600 hover:bg-green-500 text-white disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer flex items-center gap-1.5"
          >
            {running ? (
              <>
                <span className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Running...
              </>
            ) : (
              <>
                <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M8 5v14l11-7z" />
                </svg>
                Run Code
              </>
            )}
          </button>
        </div>

        {/* Code Editor */}
        <div className="flex-1 min-h-0 relative">
          <div className="absolute inset-0 overflow-auto">
          <CodeMirror
            key={questionId}
            ref={editorRef}
            value={fullCode}
            onChange={handleChange}
            extensions={cmExtensions}
            theme={oneDark}
            height="100%"
            style={{ height: "100%", overflow: "auto" }}
            basicSetup={{
              lineNumbers: true,
              highlightActiveLineGutter: true,
              highlightActiveLine: true,
              foldGutter: true,
              indentOnInput: true,
              tabSize: 4,
            }}
          />
          </div>
        </div>

        {/* Results Panel */}
        <div className="h-48 flex-shrink-0 border-t border-gray-700 bg-gray-800 flex flex-col overflow-hidden">
          {/* Tabs */}
          <div className="flex items-center border-b border-gray-700 px-3">
            <button
              onClick={() => setActiveTab("testcases")}
              className={`px-3 py-2 text-xs font-medium border-b-2 cursor-pointer ${
                activeTab === "testcases"
                  ? "border-blue-500 text-blue-300"
                  : "border-transparent text-gray-400 hover:text-gray-200"
              }`}
            >
              Test Cases
            </button>
            <button
              onClick={() => setActiveTab("results")}
              className={`px-3 py-2 text-xs font-medium border-b-2 cursor-pointer ${
                activeTab === "results"
                  ? "border-blue-500 text-blue-300"
                  : "border-transparent text-gray-400 hover:text-gray-200"
              }`}
            >
              Results
              {results && (
                <span className={`ml-1.5 px-1.5 py-0.5 rounded text-[10px] ${
                  passedCount === totalCount ? "bg-green-900 text-green-300" : "bg-red-900 text-red-300"
                }`}>
                  {passedCount}/{totalCount}
                </span>
              )}
            </button>
          </div>

          {/* Tab Content */}
          <div className="flex-1 overflow-y-auto p-3">
            {activeTab === "testcases" && (
              <div className="space-y-2">
                {testCases.length === 0 ? (
                  <p className="text-xs text-gray-500">No sample test cases available.</p>
                ) : (
                  testCases.map((tc, idx) => (
                    <div key={tc.id} className="flex items-start gap-3 text-xs">
                      <span className="text-gray-500 w-6 shrink-0">#{idx + 1}</span>
                      <span className="text-gray-400">
                        Input: <code className="text-gray-300">{tc.input_data || "(none)"}</code>
                        {" → "}
                        Expected: <code className="text-gray-300">{tc.expected_output}</code>
                      </span>
                    </div>
                  ))
                )}
              </div>
            )}

            {activeTab === "results" && (
              <div className="space-y-2">
                {!results ? (
                  <p className="text-xs text-gray-500">Run your code to see results.</p>
                ) : running ? (
                  <p className="text-xs text-gray-400">Running...</p>
                ) : (
                  results.map((r, idx) => (
                    <div
                      key={r.test_case_id + idx}
                      className={`p-2 rounded border text-xs ${
                        r.passed
                          ? "border-green-800 bg-green-900/20"
                          : "border-red-800 bg-red-900/20"
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`font-medium ${r.passed ? "text-green-400" : "text-red-400"}`}>
                          {r.passed ? "✓ Passed" : "✗ Failed"}
                        </span>
                        <span className="text-gray-500">Test Case {idx + 1}</span>
                      </div>
                      {!r.passed && (
                        <div className="space-y-1 mt-1">
                          {r.input_data && (
                            <div className="text-gray-400">
                              Input: <code className="text-gray-300">{r.input_data}</code>
                            </div>
                          )}
                          <div className="text-gray-400">
                            Expected: <code className="text-green-300">{r.expected_output}</code>
                          </div>
                          <div className="text-gray-400">
                            Got: <code className="text-red-300">{r.actual_output || "(no output)"}</code>
                          </div>
                          {r.error && (
                            <div className="text-red-400 mt-1">
                              Error: {r.error}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
