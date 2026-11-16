"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Mic, MicOff, PhoneOff } from "lucide-react";
import { api, IS_DEMO } from "@/lib/api";
import { cn } from "@/lib/format";
import { Avatar } from "./ui";

type Phase = "permission" | "ringing" | "connected" | "ended" | "denied";

/**
 * Voice call UI. Asks for microphone consent, opens an authorised call session,
 * then hands the stream to WebRTC signalling (backend owned). No recording.
 */
export function CallOverlay({ open, onClose, conversationId, peerName }: { open: boolean; onClose: () => void; conversationId: string; peerName: string }) {
  const [phase, setPhase] = useState<Phase>("permission");
  const [muted, setMuted] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const stream = useRef<MediaStream | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      try {
        stream.current = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (cancelled) return;
        await api.startCall(conversationId);
        setPhase("ringing");
        if (IS_DEMO) setTimeout(() => !cancelled && setPhase((p) => (p === "ringing" ? "connected" : p)), 2600);
      } catch {
        if (!cancelled) setPhase("denied");
      }
    })();
    return () => {
      cancelled = true;
      stream.current?.getTracks().forEach((t) => t.stop());
      stream.current = null;
    };
  }, [open, conversationId]);

  useEffect(() => {
    if (phase !== "connected") return;
    const t = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [phase]);

  useEffect(() => {
    stream.current?.getAudioTracks().forEach((t) => (t.enabled = !muted));
  }, [muted]);

  function close() {
    setPhase("permission");
    setSeconds(0);
    setMuted(false);
    onClose();
  }

  function end() {
    stream.current?.getTracks().forEach((t) => t.stop());
    setPhase("ended");
    setTimeout(close, 700);
  }

  const label = {
    permission: "Allow microphone access to call",
    ringing: "Calling…",
    connected: `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`,
    ended: "Call ended",
    denied: "Microphone access was blocked. Allow it in your browser settings and try again.",
  }[phase];

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          role="dialog"
          aria-modal="true"
          aria-label={`Voice call with ${peerName}`}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[70] flex flex-col items-center justify-between bg-paper px-6 py-16 text-ink"
        >
          <div className="flex flex-col items-center text-center">
            <div className={"rounded-full"}>
              <Avatar name={peerName} size={112} />
            </div>
            <p className="font-semiwide mt-6 text-3xl font-bold">{peerName}</p>
            <p className="tnum mt-2 max-w-xs text-ink-3" aria-live="polite">
              {label}
            </p>
            {IS_DEMO && phase === "connected" && <p className="mt-3 text-xs text-ink-3">Demo mode: the other side is simulated.</p>}
          </div>
          <div className="flex items-center gap-6">
            {phase !== "denied" && (
              <button
                onClick={() => setMuted((m) => !m)}
                aria-pressed={muted}
                aria-label={muted ? "Unmute" : "Mute"}
                className={cn("grid size-16 place-items-center rounded-full", muted ? "bg-stellar text-white" : "bg-plaster-2 text-ink hover:bg-line")}
              >
                {muted ? <MicOff className="size-6" /> : <Mic className="size-6" />}
              </button>
            )}
            <button onClick={phase === "denied" ? close : end} aria-label="End call" className="grid size-20 place-items-center rounded-full bg-clay text-white hover:brightness-110">
              <PhoneOff className="size-7" />
            </button>
          </div>
          <p className="text-xs text-ink-3">Calls are not recorded. Your phone number is not shared.</p>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
