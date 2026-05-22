import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

type SpeechToTextControlProps = {
  disabled?: boolean;
  onTranscriptChange?: (text: string) => void;
  onError?: (error: string) => void;
  onStart?: () => void;
  onStop?: () => void;
};

export type SpeechToTextControlHandle = {
  start: () => void;
  stop: () => void;
};

type SpeechRecognitionType = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: any) => void) | null;
  onerror: ((event: any) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

declare global {
  interface Window {
    webkitSpeechRecognition?: new () => SpeechRecognitionType;
    SpeechRecognition?: new () => SpeechRecognitionType;
  }
}

const SpeechToTextControl = forwardRef<SpeechToTextControlHandle, SpeechToTextControlProps>(
  function SpeechToTextControl({ disabled = false, onTranscriptChange, onError, onStart, onStop }, ref) {
    const [isRecording, setIsRecording] = useState(false);
    const [isSupported, setIsSupported] = useState(false);
    const recognitionRef = useRef<SpeechRecognitionType | null>(null);
    const onTranscriptChangeRef = useRef(onTranscriptChange);
    const onErrorRef = useRef(onError);
    const onStartRef = useRef(onStart);
    const onStopRef = useRef(onStop);

    useEffect(() => { onTranscriptChangeRef.current = onTranscriptChange; }, [onTranscriptChange]);
    useEffect(() => { onErrorRef.current = onError; }, [onError]);
    useEffect(() => { onStartRef.current = onStart; }, [onStart]);
    useEffect(() => { onStopRef.current = onStop; }, [onStop]);

    useEffect(() => {
      const SpeechApi = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SpeechApi) {
        setIsSupported(false);
        return;
      }
      setIsSupported(true);

      const recognition = new SpeechApi();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = "en-US";

      recognition.onresult = (event: any) => {
        let finalText = "";
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          const result = event.results[i];
          if (result.isFinal) {
            finalText += `${result[0].transcript} `;
          }
        }
        const clean = finalText.trim();
        if (clean) {
          onTranscriptChangeRef.current?.(clean);
        }
      };

      recognition.onerror = (event: any) => {
        onErrorRef.current?.(String(event?.error || "Speech recognition failed"));
      };

      recognition.onend = () => {
        setIsRecording(false);
        onStopRef.current?.();
      };

      recognitionRef.current = recognition;
      return () => {
        recognition.stop();
        recognitionRef.current = null;
      };
    }, []);

    const startRecording = () => {
      if (!recognitionRef.current || disabled) return;
      if (isRecording) return;
      try {
        recognitionRef.current.start();
        setIsRecording(true);
        onStartRef.current?.();
      } catch {
        onErrorRef.current?.("Could not start speech recognition");
      }
    };

    const stopRecording = () => {
      if (!recognitionRef.current || !isRecording) return;
      recognitionRef.current.stop();
      // onend handler will call onStopRef and setIsRecording(false)
    };

    useImperativeHandle(ref, () => ({
      start: startRecording,
      stop: stopRecording,
    }));

    const toggleRecording = () => {
      if (isRecording) {
        stopRecording();
      } else {
        startRecording();
      }
    };

    if (!isSupported) {
      return (
        <button
          type="button"
          disabled
          className="h-9 px-3 text-xs font-medium rounded-[var(--radius-sm)] bg-gray-100 text-gray-400"
          title="Speech recognition not available in this browser"
        >
          STT Unavailable
        </button>
      );
    }

    return (
      <button
        type="button"
        onClick={toggleRecording}
        disabled={disabled}
        className={`h-9 px-3 text-xs font-medium rounded-[var(--radius-sm)] transition-colors ${
          isRecording
            ? "bg-red-50 text-red-700 hover:bg-red-100"
            : "bg-blue-50 text-[var(--color-primary)] hover:bg-blue-100"
        } ${disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
        title={isRecording ? "Stop speech-to-text" : "Start speech-to-text"}
      >
        {isRecording ? "Stop Mic" : "Start Mic"}
      </button>
    );
  }
);

export default SpeechToTextControl;
