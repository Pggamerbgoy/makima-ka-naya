import { useCallback, useEffect, useRef, useState } from 'react';
import { Mic, Square, Volume2, Sparkles, Radio } from 'lucide-react';
import type { UiSettings } from '../types';
import { websocketUrl } from '../api';
import { Button } from './ui';

type WakeRecognizer = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  start: () => void;
  stop: () => void;
};
type WakeRecognizerCtor = new () => WakeRecognizer;

type VoiceState = 'off' | 'ambient' | 'live' | 'speaking' | 'followup' | 'error';

function playAudioChime(type: 'wake' | 'standby'): void {
  try {
    const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.connect(gain);
    gain.connect(ctx.destination);
    const now = ctx.currentTime;
    if (type === 'wake') {
      // 880Hz -> 1320Hz ascending two-tone sci-fi wake chime
      osc.frequency.setValueAtTime(880, now);
      osc.frequency.exponentialRampToValueAtTime(1320, now + 0.12);
      gain.gain.setValueAtTime(0.18, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.28);
      osc.start(now);
      osc.stop(now + 0.28);
    } else {
      // 1320Hz -> 880Hz soft descending standby cue
      osc.frequency.setValueAtTime(1320, now);
      osc.frequency.exponentialRampToValueAtTime(880, now + 0.14);
      gain.gain.setValueAtTime(0.12, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.32);
      osc.start(now);
      osc.stop(now + 0.32);
    }
  } catch {
    // AudioContext blocked or silent environment
  }
}

function downsamplePcm(input: Float32Array, fromRate: number, toRate = 16000): ArrayBuffer {
  const ratio = fromRate / toRate;
  const output = new Int16Array(Math.round(input.length / ratio));
  for (let index = 0; index < output.length; index += 1) {
    output[index] = Math.max(-1, Math.min(1, input[Math.min(Math.floor(index * ratio), input.length - 1)])) * 0x7fff;
  }
  return output.buffer;
}

export function VoiceControl({ settings, onNotice }: { settings: UiSettings; onNotice?: (message: string) => void }) {
  const [state, setState] = useState<VoiceState>('off');
  const [notice, setNotice] = useState('Say “Makima” or tap to start');
  const [followupSeconds, setFollowupSeconds] = useState(0);

  const socket = useRef<WebSocket | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const audioContext = useRef<AudioContext | null>(null);
  const processor = useRef<ScriptProcessorNode | null>(null);
  const wake = useRef<WakeRecognizer | null>(null);
  const voiceReady = useRef(false);
  const nextAudioTime = useRef(0);
  const isSpeaking = useRef(false);
  const stateRef = useRef<VoiceState>('off');
  const followupTimer = useRef<number | null>(null);
  const activeAudioSources = useRef<AudioBufferSourceNode[]>([]);

  stateRef.current = state;

  const notify = useCallback((message: string, isToast = false) => {
    setNotice(message);
    if (isToast) onNotice?.(message);
  }, [onNotice]);

  const stopAudioSources = useCallback(() => {
    activeAudioSources.current.forEach((src) => {
      try { src.stop(); } catch { /* already stopped */ }
    });
    activeAudioSources.current = [];
    isSpeaking.current = false;
    nextAudioTime.current = 0;
  }, []);

  const stopWake = useCallback(() => {
    if (wake.current) {
      wake.current.onend = null;
      wake.current.onerror = null;
      wake.current.onresult = null;
      try { wake.current.stop(); } catch { /* already stopped */ }
      wake.current = null;
    }
  }, []);

  const stopLive = useCallback(() => {
    if (followupTimer.current !== null) {
      window.clearInterval(followupTimer.current);
      followupTimer.current = null;
    }
    voiceReady.current = false;
    stopAudioSources();
    processor.current?.disconnect();
    processor.current = null;
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    if (audioContext.current?.state !== 'closed') {
      audioContext.current?.close().catch(() => {});
    }
    audioContext.current = null;
    if (socket.current?.readyState === WebSocket.OPEN) {
      socket.current.send(JSON.stringify({ type: 'stop' }));
    }
    socket.current?.close();
    socket.current = null;
    stopWake();
    setState('off');
    notify('Jarvis paused — tap to start');
  }, [notify, stopAudioSources, stopWake]);

  const playPcm = useCallback(async (payload: ArrayBuffer | Blob) => {
    const bytes = payload instanceof Blob ? await payload.arrayBuffer() : payload;
    const context = audioContext.current;
    if (!context || context.state === 'closed') return;
    const pcm = new Int16Array(bytes);
    const buffer = context.createBuffer(1, pcm.length, 24000);
    const channel = buffer.getChannelData(0);
    pcm.forEach((value, index) => {
      channel[index] = value / 0x7fff;
    });
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    const startAt = Math.max(context.currentTime, nextAudioTime.current);
    source.start(startAt);
    nextAudioTime.current = startAt + buffer.duration;

    isSpeaking.current = true;
    setState('speaking');
    notify('Makima is speaking…');

    activeAudioSources.current.push(source);
    source.onended = () => {
      activeAudioSources.current = activeAudioSources.current.filter((s) => s !== source);
      if (activeAudioSources.current.length === 0) {
        isSpeaking.current = false;
      }
    };
  }, [notify]);

  // Transitions to ambient passive wake listening
  const startAmbient = useCallback(() => {
    stopLive();
    const constructor = (window as unknown as { SpeechRecognition?: WakeRecognizerCtor; webkitSpeechRecognition?: WakeRecognizerCtor }).SpeechRecognition ||
      (window as unknown as { webkitSpeechRecognition?: WakeRecognizerCtor }).webkitSpeechRecognition;

    if (!constructor) {
      notify('Jarvis ambient active (Direct mode)');
      return;
    }

    const recognizer = new constructor();
    recognizer.continuous = true;
    recognizer.interimResults = true;
    recognizer.lang = settings.language === 'hi' ? 'hi-IN' : 'en-IN';

    const wakeWords = (settings.wake_words && settings.wake_words.length > 0)
      ? settings.wake_words.map((w) => w.trim().toLowerCase())
      : ['makima', 'hey makima', 'jarvis', 'suno makima'];

    recognizer.onresult = (event) => {
      const text = Array.from({ length: event.results.length }, (_, index) => event.results[index][0].transcript)
        .join(' ')
        .toLowerCase();

      const matched = wakeWords.some((word) => text.includes(word));
      if (matched && stateRef.current !== 'live' && stateRef.current !== 'speaking') {
        playAudioChime('wake');
        stopWake();
        // Trigger live session immediately without button click
        void startLive();
      }
    };

    recognizer.onerror = (ev) => {
      if (ev.error === 'no-speech' || ev.error === 'aborted') {
        // Normal ambient silence — do not alarm user
        return;
      }
      notify('Wake listening reconnecting…');
    };

    recognizer.onend = () => {
      // Automatic watchdog: seamlessly restart recognition on silence timeouts
      if (stateRef.current === 'ambient' || stateRef.current === 'off') {
        window.setTimeout(() => {
          if (wake.current === recognizer && (stateRef.current === 'ambient' || settings.jarvis_mode)) {
            try { recognizer.start(); } catch { /* restarting */ }
          }
        }, 220);
      }
    };

    wake.current = recognizer;
    try {
      recognizer.start();
      setState('ambient');
      notify('Jarvis listening for “Makima”');
    } catch {
      notify('Tap Voice to allow microphone');
    }
  }, [notify, settings.jarvis_mode, settings.language, settings.wake_words, stopLive, stopWake]);

  const startFollowupWindow = useCallback(() => {
    const totalSeconds = Math.max(5, settings.followup_window_s || 10);
    setFollowupSeconds(totalSeconds);
    setState('followup');
    notify(`Follow-up window (${totalSeconds}s) — ask another question`);

    if (followupTimer.current !== null) {
      window.clearInterval(followupTimer.current);
    }

    let remaining = totalSeconds;
    followupTimer.current = window.setInterval(() => {
      remaining -= 1;
      setFollowupSeconds(remaining);
      if (remaining <= 0) {
        if (followupTimer.current !== null) {
          window.clearInterval(followupTimer.current);
          followupTimer.current = null;
        }
        playAudioChime('standby');
        notify('Returning to ambient guard…');
        startAmbient();
      } else {
        notify(`Follow-up window (${remaining}s) — ask another question`);
      }
    }, 1000);
  }, [notify, settings.followup_window_s, startAmbient]);

  const startLive = useCallback(async () => {
    try {
      if (followupTimer.current !== null) {
        window.clearInterval(followupTimer.current);
        followupTimer.current = null;
      }
      stopWake();
      notify('Connecting to Gemini Live…');

      const media = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      stream.current = media;
      const context = new AudioContext();
      await context.resume();
      audioContext.current = context;

      const ws = new WebSocket(websocketUrl('/ws/voice'));
      ws.binaryType = 'arraybuffer';
      socket.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({
          type: 'start',
          model: 'gemini-3.8-live',
          voice_name: settings.voice_name || 'Aoede',
        }));
      };

      ws.onmessage = (event) => {
        if (typeof event.data !== 'string') {
          void playPcm(event.data);
          return;
        }
        try {
          const message = JSON.parse(event.data) as { type: string; message?: string; text?: string };
          if (message.type === 'voice_ready') {
            voiceReady.current = true;
            setState('live');
            notify('Listening — say your command');
          } else if (message.type === 'text') {
            notify(message.text || 'Listening…');
          } else if (message.type === 'turn_complete') {
            // Model finished speaking its turn! Enter multi-turn follow-up window
            startFollowupWindow();
          } else if (message.type === 'interrupted') {
            // User interrupted Makima (barge-in confirmed by model)
            stopAudioSources();
            setState('live');
            notify('Listening to you…');
          } else if (message.type === 'voice_error') {
            setState('error');
            notify(message.message || 'Gemini Live connection failed', true);
          }
        } catch {
          setState('error');
          notify('Invalid voice response', true);
        }
      };

      ws.onerror = () => {
        setState('error');
        notify('Gemini Live connection failed', true);
      };

      const source = context.createMediaStreamSource(media);
      const node = context.createScriptProcessor(4096, 1, 1);
      const silent = context.createGain();
      silent.gain.value = 0;
      source.connect(node);
      node.connect(silent);
      silent.connect(context.destination);

      node.onaudioprocess = (event) => {
        const inputData = event.inputBuffer.getChannelData(0);
        // Measure audio input energy
        let sumSquares = 0;
        for (let i = 0; i < inputData.length; i += 1) {
          sumSquares += inputData[i] * inputData[i];
        }
        const rms = Math.sqrt(sumSquares / inputData.length);

        // Barge-in: If Makima is currently speaking and user speaks loudly, halt speaker
        if (isSpeaking.current && rms > 0.04) {
          stopAudioSources();
          setState('live');
          notify('Listening to you…');
        }

        // In follow-up window: If user speaks, clear the timeout and transition to active live
        if (stateRef.current === 'followup' && rms > 0.035) {
          if (followupTimer.current !== null) {
            window.clearInterval(followupTimer.current);
            followupTimer.current = null;
          }
          setState('live');
          notify('Listening to follow-up…');
        }

        // Stream audio frames to Gemini Live WebSocket
        if (voiceReady.current && ws.readyState === WebSocket.OPEN) {
          ws.send(downsamplePcm(inputData, context.sampleRate));
        }
      };

      processor.current = node;
    } catch (error) {
      setState('error');
      notify(
        error instanceof DOMException && error.name === 'NotAllowedError'
          ? 'Microphone permission required'
          : 'Voice connection failed',
        true,
      );
    }
  }, [notify, playPcm, settings.voice_name, startFollowupWindow, stopAudioSources, stopWake]);

  // Auto-engage Jarvis Mode on mount if enabled
  useEffect(() => {
    if (settings.jarvis_mode && settings.auto_listen_on_start) {
      startAmbient();
    }
    return () => {
      stopLive();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const active = state === 'ambient' || state === 'live' || state === 'speaking' || state === 'followup';

  const handleClick = () => {
    if (state === 'live' || state === 'speaking' || state === 'followup') {
      // User tapped button during active conversation: transition back to ambient standby
      startAmbient();
    } else if (state === 'ambient') {
      // User tapped button while ambient: immediately activate direct Live mode (no wake word needed)
      void startLive();
    } else {
      // Off or error: directly start Live voice conversation so user can speak immediately
      void startLive();
    }
  };

  const getButtonTitle = () => {
    if (state === 'live') return 'Live with Makima — Click to pause';
    if (state === 'speaking') return 'Makima is speaking — Click to pause';
    if (state === 'followup') return `Follow-up window (${followupSeconds}s) — Click to return to standby`;
    if (state === 'ambient') return 'Jarvis listening for “Makima” — Click to speak directly';
    return 'Click to talk with Makima (or say “Hey Makima”)';
  };

  return (
    <div className="voice-control">
      <Button
        className={`voice-button ${active ? `voice-${state}` : ''}`}
        title={getButtonTitle()}
        aria-label={getButtonTitle()}
        onClick={handleClick}
      >
        {state === 'speaking' ? (
          <Volume2 size={16} />
        ) : state === 'followup' ? (
          <Sparkles size={16} />
        ) : state === 'ambient' ? (
          <Radio size={16} />
        ) : (
          <Mic size={16} />
        )}
        {state === 'speaking'
          ? 'Speaking'
          : state === 'followup'
          ? `Follow-up ${followupSeconds}s`
          : state === 'live'
          ? 'Live'
          : state === 'ambient'
          ? 'Jarvis ON'
          : 'Jarvis'}
        {active && (
          <span className="voice-wave">
            <i />
            <i />
            <i />
          </span>
        )}
      </Button>
      {active && <small className="wake-hint">{notice}</small>}
      {state === 'error' && (
        <Button className="voice-retry" onClick={() => void startLive()}>
          <Square size={12} /> Retry
        </Button>
      )}
    </div>
  );
}
