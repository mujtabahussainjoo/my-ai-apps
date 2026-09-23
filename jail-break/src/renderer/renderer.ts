type Provider = "openai" | "anthropic";
type ChatRole = "user" | "assistant" | "caller";
interface ChatMsg {
  role: ChatRole;
  text: string;
}

const LS_KEY = "visible-assistant-key-";
const LS_MODEL = "visible-assistant-model-";
const LS_PROVIDER = "visible-assistant-provider";

const providerEl = document.getElementById("provider") as HTMLSelectElement;
const modelEl = document.getElementById("model") as HTMLInputElement;
const apiKeyEl = document.getElementById("apiKey") as HTMLInputElement;
const saveBtn = document.getElementById("saveKey") as HTMLButtonElement;
const chatEl = document.getElementById("chat") as HTMLElement;
const inputEl = document.getElementById("input") as HTMLInputElement;
const sendBtn = document.getElementById("sendBtn") as HTMLButtonElement;
const shotBtn = document.getElementById("shotBtn") as HTMLButtonElement;
const readBtn = document.getElementById("readBtn") as HTMLButtonElement;
const pickerWrap = document.getElementById("sourcePicker") as HTMLElement;
const sourceList = document.getElementById("sourceList") as HTMLElement;
const pickerClose = document.getElementById("pickerClose") as HTMLButtonElement;
const listenBtn = document.getElementById("listenBtn") as HTMLButtonElement;
const speakBtn = document.getElementById("speakBtn") as HTMLButtonElement;
const hideBtn = document.getElementById("hideBtn") as HTMLButtonElement;
const minBtn = document.getElementById("minBtn") as HTMLButtonElement | null;
const previewWrap = document.getElementById("previewWrap") as HTMLElement;
const previewImg = document.getElementById("preview") as HTMLImageElement;
const clearImgBtn = document.getElementById("clearImg") as HTMLButtonElement;
const callerBtn = document.getElementById("callerBtn") as HTMLButtonElement;
const callerStatus = document.getElementById("callerStatus") as HTMLElement;
const stayBtn = document.getElementById("stayBtn") as HTMLButtonElement;
let stayOn = false;

const chatHistory: ChatMsg[] = [];
let attachedImage: string | null = null; // dataURL
let lastAnswer = "";
// 🎤 Listen uses mic recording + OpenAI Whisper (BYOK). Web Speech API is
// intentionally NOT used: in Electron it streams to Google's speech service,
// which fails without a Speech API key and logs:
//   chunked_data_pipe_upload_data_stream.cc OnSizeReceived failed, Error: -2
let mediaRecorder: MediaRecorder | null = null;
let micStream: MediaStream | null = null;
let audioChunks: Blob[] = [];
let listening = false;
let transcribing = false;

const DEFAULTS: Record<Provider, string> = {
  openai: "gpt-4o-mini",
  anthropic: "claude-3-5-sonnet-latest",
};

function currentProvider(): Provider {
  return (providerEl.value as Provider) || "openai";
}

function loadSettings(): void {
  const savedProvider = localStorage.getItem(LS_PROVIDER) as Provider | null;
  if (savedProvider) providerEl.value = savedProvider;
  const p = currentProvider();
  modelEl.value = localStorage.getItem(LS_MODEL + p) || DEFAULTS[p];
  apiKeyEl.value = localStorage.getItem(LS_KEY + p) || "";
}

function saveSettings(): void {
  const p = currentProvider();
  localStorage.setItem(LS_PROVIDER, p);
  localStorage.setItem(LS_MODEL + p, modelEl.value.trim() || DEFAULTS[p]);
  localStorage.setItem(LS_KEY + p, apiKeyEl.value.trim());
  addMsg("assistant", `Saved ${p} settings locally.`);
}

function addMsg(role: ChatRole | "err", text: string): void {
  // "caller" renders its own bubble but is stored as user so the AI answers it.
  const div = document.createElement("div");
  div.className = `msg ${role === "err" ? "err" : role}`;
  div.textContent = role === "caller" ? `Caller: ${text}` : text;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
  if (role === "user" || role === "assistant") chatHistory.push({ role, text });
  else if (role === "caller") chatHistory.push({ role: "user", text: `Caller said: ${text}` });
}

function dataUrlToBase64(dataUrl: string): { mime: string; data: string } {
  const [head, data] = dataUrl.split(",");
  const mime = (head.match(/data:(.*?);/) || [])[1] || "image/png";
  return { mime, data };
}

async function callOpenAI(apiKey: string, model: string, prompt: string): Promise<string> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const content: any[] = [{ type: "text", text: prompt }];
  if (attachedImage) content.push({ type: "image_url", image_url: { url: attachedImage } });

  const res = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({
      model,
      messages: [
        ...chatHistory.slice(-10).map((m: ChatMsg) => ({ role: m.role, content: m.text })),
        { role: "user", content },
      ],
      max_tokens: 1000,
    }),
  });
  if (!res.ok) throw new Error(`OpenAI ${res.status}: ${await res.text()}`);
  const json = await res.json();
  return json.choices?.[0]?.message?.content ?? "(empty response)";
}

async function callAnthropic(apiKey: string, model: string, prompt: string): Promise<string> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const content: any[] = [];
  if (attachedImage) {
    const { mime, data } = dataUrlToBase64(attachedImage);
    const media = mime.startsWith("image/") ? mime : "image/png";
    content.push({
      type: "image",
      source: { type: "base64", media_type: media, data },
    });
  }
  content.push({ type: "text", text: prompt });

  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
      "anthropic-dangerous-direct-browser-access": "true",
    },
    body: JSON.stringify({
      model,
      max_tokens: 1000,
      messages: [{ role: "user", content }],
    }),
  });
  if (!res.ok) throw new Error(`Anthropic ${res.status}: ${await res.text()}`);
  const json = await res.json();
  const blocks = json.content || [];
  return blocks.map((b: { text?: string }) => b.text || "").join("\n") || "(empty response)";
}

async function send(): Promise<void> {
  const p = currentProvider();
  const apiKey = (localStorage.getItem(LS_KEY + p) || apiKeyEl.value || "").trim();
  const model = (modelEl.value || localStorage.getItem(LS_MODEL + p) || DEFAULTS[p]).trim();
  const prompt = inputEl.value.trim();
  if (!prompt && !attachedImage) return;
  if (!apiKey) {
    addMsg("err", "Missing API key. Paste it above and click Save.");
    return;
  }
  // Image with no typed question: ask the model to read + analyze it and
  // answer anything visible, instead of sending a bare "(image only)".
  const effectivePrompt =
    prompt ||
    "Read this screen/image carefully. Transcribe the key text shown, then analyze it and answer any questions visible in it. If there is no explicit question, summarize what matters most.";
  addMsg("user", prompt || "(analyzing attached image)");
  inputEl.value = "";
  sendBtn.disabled = true;
  stopSpeaking();
  try {
    const reply = p === "openai" ? await callOpenAI(apiKey, model, effectivePrompt) : await callAnthropic(apiKey, model, effectivePrompt);
    lastAnswer = reply;
    addMsg("assistant", reply);
  } catch (e) {
    addMsg("err", e instanceof Error ? e.message : String(e));
  } finally {
    sendBtn.disabled = false;
    attachedImage = null;
    previewWrap.classList.add("hidden");
  }
}

async function captureScreenshot(): Promise<void> {
  try {
    // Visible, permission-prompted capture. Shows in screenshare / taskbar.
    const stream = await navigator.mediaDevices.getDisplayMedia({ video: true });
    const video = document.createElement("video");
    video.srcObject = stream;
    await video.play();
    const canvas = document.createElement("canvas");
    const scale = 1280 / video.videoWidth;
    canvas.width = 1280;
    canvas.height = Math.round(video.videoHeight * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas unavailable");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    stream.getTracks().forEach((t) => t.stop());
    attachedImage = canvas.toDataURL("image/png");
    previewImg.src = attachedImage;
    previewWrap.classList.remove("hidden");
    addMsg("assistant", "Screenshot attached. Press Send to analyze it, or type a question first.");
  } catch (e) {
    addMsg("err", `Screenshot cancelled/failed: ${e instanceof Error ? e.message : String(e)}`);
  }
}

interface ScreenSource {
  id: string;
  name: string;
  thumbnail: string;
}

async function openSourcePicker(): Promise<void> {
  let sources: ScreenSource[];
  try {
    sources = await window.assistant.listScreenSources();
  } catch (e) {
    addMsg("err", `Could not list windows: ${e instanceof Error ? e.message : String(e)}`);
    return;
  }
  sourceList.innerHTML = "";
  if (!sources.length) {
    addMsg("err", "No windows found to read. Open a browser window and try again.");
    return;
  }
  for (const s of sources) {
    const btn = document.createElement("button");
    btn.className = "source-item";
    btn.title = s.name;
    if (s.thumbnail) {
      const img = document.createElement("img");
      img.src = s.thumbnail;
      img.alt = "";
      btn.appendChild(img);
    }
    const label = document.createElement("span");
    label.textContent = s.name || "(unnamed window)";
    btn.appendChild(label);
    btn.addEventListener("click", () => {
      pickerWrap.classList.add("hidden");
      void captureWindowSource(s.id, s.name);
    });
    sourceList.appendChild(btn);
  }
  pickerWrap.classList.remove("hidden");
}

async function captureWindowSource(sourceId: string, sourceName: string): Promise<void> {
  let stream: MediaStream | null = null;
  try {
    // Desktop (not display-media) constraints: bypasses main's auto-grant
    // handler so the user-picked window is captured, not the primary screen.
    stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        mandatory: {
          chromeMediaSource: "desktop",
          chromeMediaSourceId: sourceId,
        },
      } as MediaTrackConstraints,
    } as MediaStreamConstraints);
    const video = document.createElement("video");
    video.srcObject = stream;
    await video.play();
    const canvas = document.createElement("canvas");
    const scale = 1280 / video.videoWidth;
    canvas.width = 1280;
    canvas.height = Math.round(video.videoHeight * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas unavailable");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    attachedImage = canvas.toDataURL("image/png");
    previewImg.src = attachedImage;
    previewWrap.classList.remove("hidden");
    addMsg("assistant", `Screen read from “${sourceName || "window"}”. Press Send to analyze it, or type a question first.`);
  } catch (e) {
    addMsg("err", `Screen read failed: ${e instanceof Error ? e.message : String(e)}`);
  } finally {
    try {
      stream?.getTracks().forEach((t) => t.stop());
    } catch {
      /* ignore */
    }
  }
}

function getTranscriptionKey(): string {
  // Whisper transcription always uses the saved OpenAI key, even when the
  // chat provider is Anthropic.
  return (
    localStorage.getItem(LS_KEY + "openai") ||
    (currentProvider() === "openai" ? apiKeyEl.value : "") ||
    ""
  ).trim();
}

function pickMimeType(): string {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "",
  ];
  for (const t of candidates) {
    if (!t) return "";
    try {
      if (MediaRecorder.isTypeSupported(t)) return t;
    } catch {
      /* ignore */
    }
  }
  return "";
}

function setListeningUI(on: boolean, busyLabel = false): void {
  listening = on;
  listenBtn.classList.toggle("listening", on);
  if (transcribing || busyLabel) {
    listenBtn.textContent = "…";
    listenBtn.title = "Transcribing…";
  } else {
    listenBtn.textContent = on ? "⏺" : "🎤";
    listenBtn.title = on ? "Stop listening" : "Listen (voice input)";
  }
}

function stopMicTracks(): void {
  try {
    micStream?.getTracks().forEach((t) => t.stop());
  } catch {
    /* ignore */
  }
  micStream = null;
}

async function transcribeRecording(blob: Blob): Promise<string> {
  const key = getTranscriptionKey();
  if (!key) {
    throw new Error(
      "No OpenAI key for 🎤 transcription. Switch Provider to OpenAI, paste key, Save — then tap 🎤 again. (Chat can stay on Anthropic.)"
    );
  }
  // Whisper validates the file extension, so it must match the container.
  const t = (blob.type || "").toLowerCase();
  const ext = t.includes("mp4") || t.includes("m4a")
    ? "audio.mp4"
    : t.includes("ogg") || t.includes("oga")
      ? "audio.ogg"
      : t.includes("wav")
        ? "audio.wav"
        : t.includes("mpeg") || t.includes("mpga") || t.includes("mp3")
          ? "audio.mp3"
          : "audio.webm";
  const form = new FormData();
  form.append("file", blob, ext);
  form.append("model", "whisper-1");
  form.append("language", "en");
  const res = await fetch("https://api.openai.com/v1/audio/transcriptions", {
    method: "POST",
    headers: { Authorization: `Bearer ${key}` },
    body: form,
  });
  if (!res.ok) throw new Error(`Transcription ${res.status}: ${await res.text()}`);
  const json = (await res.json()) as { text?: string };
  return (json.text || "").trim();
}

async function toggleListen(): Promise<void> {
  if (transcribing) return;
  if (listening && mediaRecorder) {
    // Second tap: stop recording -> onstop transcribes.
    try {
      mediaRecorder.stop();
    } catch {
      /* already stopped */
    }
    return;
  }
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    addMsg("err", "Mic blocked. Allow microphone for this app (Windows Settings > Privacy > Microphone), then tap 🎤 again.");
    return;
  }
  const mimeType = pickMimeType();
  let rec: MediaRecorder;
  try {
    rec = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
  } catch (e) {
    stopMicTracks();
    addMsg("err", `Could not start recorder: ${e instanceof Error ? e.message : String(e)}`);
    return;
  }
  micStream = stream;
  mediaRecorder = rec;
  audioChunks = [];
  rec.ondataavailable = (e: BlobEvent): void => {
    if (e.data && e.data.size > 0) audioChunks.push(e.data);
  };
  rec.onerror = (): void => {
    addMsg("err", "Recording failed. Check mic and try again.");
  };
  rec.onstop = (): void => {
    const chunks = audioChunks;
    audioChunks = [];
    const mime = rec.mimeType || mimeType || "audio/webm";
    stopMicTracks();
    mediaRecorder = null;
    if (!chunks.length) {
      setListeningUI(false);
      addMsg("err", "No audio captured. Try again, a little longer.");
      return;
    }
    void (async (): Promise<void> => {
      transcribing = true;
      setListeningUI(false, true);
      try {
        const text = await transcribeRecording(new Blob(chunks, { type: mime }));
        if (text) {
          inputEl.value = text;
          inputEl.focus();
          addMsg("assistant", "Heard you — review the text, then press Send.");
        } else {
          addMsg("err", "Heard nothing clear. Try again.");
        }
      } catch (e) {
        addMsg("err", e instanceof Error ? e.message : String(e));
      } finally {
        transcribing = false;
        setListeningUI(false);
      }
    })();
  };
  try {
    rec.start();
    setListeningUI(true);
    addMsg("assistant", "Listening… speak now, tap ⏺ to stop.");
  } catch (e) {
    stopMicTracks();
    mediaRecorder = null;
    setListeningUI(false);
    addMsg("err", `Could not start listening: ${e instanceof Error ? e.message : String(e)}`);
  }
}

function stopSpeaking(): void {
  try {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  } catch {
    /* no TTS */
  }
  speakBtn.classList.remove("speaking");
}

function toggleSpeak(): void {
  if (!("speechSynthesis" in window)) {
    addMsg("err", "Speech output not supported in this build.");
    return;
  }
  if (window.speechSynthesis.speaking || window.speechSynthesis.pending) {
    stopSpeaking();
    return;
  }
  const text = (lastAnswer || "").trim();
  if (!text) {
    addMsg("err", "No answer yet. Send a question first, then tap 🔊.");
    return;
  }
  try {
    const utter = new SpeechSynthesisUtterance(text);
    utter.rate = 1;
    utter.onend = (): void => speakBtn.classList.remove("speaking");
    utter.onerror = (): void => speakBtn.classList.remove("speaking");
    speakBtn.classList.add("speaking");
    window.speechSynthesis.speak(utter);
  } catch (e) {
    speakBtn.classList.remove("speaking");
    addMsg("err", `Could not speak answer: ${e instanceof Error ? e.message : String(e)}`);
  }
}

let callerStream: MediaStream | null = null;
let callerRecorder: MediaRecorder | null = null;
let callerOn = false;
let callerBusy = false;
let callerWindowTimer: number | null = null;
// Ordered transcription queue so captions stay in spoken order.
let callerQueue: Promise<void> = Promise.resolve();
// One self-contained file per window: MediaRecorder timeslice chunks after the
// first lack the WebM header, and Whisper rejects them with 400. So each
// window is a fresh recorder stopped after N ms — every blob is valid.
const CALLER_WINDOW_MS = 20000;

function setCallerUI(on: boolean, status: string): void {
  callerOn = on;
  callerBtn.classList.toggle("on", on);
  callerBtn.textContent = on ? "📞 Disable caller voice" : "📞 Enable caller voice";
  callerStatus.textContent = status;
}

function stopCallerTracks(): void {
  try {
    callerStream?.getTracks().forEach((t) => {
      try {
        t.stop();
      } catch {
        /* ignore */
      }
    });
  } catch {
    /* ignore */
  }
  callerStream = null;
}

async function transcribeCallerChunk(blob: Blob): Promise<void> {
  let text = "";
  try {
    text = await transcribeRecording(blob);
  } catch (e) {
    addMsg("err", e instanceof Error ? e.message : String(e));
    return;
  }
  text = text.trim();
  // Skip silence / Whisper "thank you" hallucinations on quiet audio.
  if (text.length < 2) return;
  if (/^(thank you|thanks|you)+\.?$/i.test(text)) return;
  addMsg("caller", text);
  // Put latest caller line in the box so Send answers it directly.
  inputEl.value = text;
  inputEl.focus();
}

async function toggleCaller(): Promise<void> {
  if (callerBusy) return;
  if (callerOn) {
    callerBusy = true;
    setCallerUI(true, "stopping…");
    await stopCallerCapture(null);
    return;
  }
  // System audio comes from main's display-media handler (primary screen +
  // loopback), so no picker tick is needed — one tap starts caller capture.
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: true,
      audio: true,
    });
  } catch (e) {
    const detail = e instanceof Error ? ` (${e.name}: ${e.message})` : "";
    addMsg("err", `Caller capture failed${detail}. Re-tap to try again.`);
    return;
  }
  const audioTracks = stream.getAudioTracks();
  // Drop video — we only want the caller's voice, not their screen.
  stream.getVideoTracks().forEach((t) => {
    try {
      t.stop();
    } catch {
      /* ignore */
    }
  });
  if (!audioTracks.length) {
    stream.getTracks().forEach((t) => {
      try {
        t.stop();
      } catch {
        /* ignore */
      }
    });
    addMsg("err", "No system audio track — loopback unavailable on this device. Try again during an active call.");
    return;
  }
  // Record AUDIO ONLY. The display stream also carries a video track (stop()
  // does not remove it), and muxing it produces video/webm which Whisper
  // rejects with 400 "Invalid file format".
  const audioOnly = new MediaStream(audioTracks);
  const mimeType = pickMimeType();
  let rec: MediaRecorder;
  try {
    rec = mimeType ? new MediaRecorder(audioOnly, { mimeType }) : new MediaRecorder(audioOnly);
  } catch (e) {
    stream.getTracks().forEach((t) => {
      try {
        t.stop();
      } catch {
        /* ignore */
      }
    });
    addMsg("err", `Could not start caller capture: ${e instanceof Error ? e.message : String(e)}`);
    return;
  }
  callerStream = stream;
  // If sharing ends externally, finish cleanly.
  audioTracks.forEach((t) => {
    t.onended = (): void => {
      if (callerOn) void stopCallerCapture("System audio ended.");
    };
  });
  setCallerUI(true, "listening…");
  addMsg("assistant", "Caller voice on — their speech will appear as “Caller: …”. Tap “Disable caller voice” to stop.");
  startCallerWindow();
}

function startCallerWindow(): void {
  if (!callerOn || !callerStream) return;
  const liveTracks = callerStream.getAudioTracks().filter((t) => t.readyState === "live");
  if (!liveTracks.length) {
    void stopCallerCapture("System audio ended.");
    return;
  }
  // Fresh audio-only stream per window => every blob is a complete valid file.
  const audioOnly = new MediaStream(liveTracks);
  const mimeType = pickMimeType();
  let rec: MediaRecorder;
  try {
    rec = mimeType ? new MediaRecorder(audioOnly, { mimeType }) : new MediaRecorder(audioOnly);
  } catch (e) {
    addMsg("err", `Could not start caller capture: ${e instanceof Error ? e.message : String(e)}`);
    void stopCallerCapture(null);
    return;
  }
  const chunks: Blob[] = [];
  callerRecorder = rec;
  rec.ondataavailable = (e: BlobEvent): void => {
    if (e.data && e.data.size > 0) chunks.push(e.data);
  };
  rec.onerror = (): void => {
    addMsg("err", "Caller recording errored on one window — continuing.");
  };
  rec.onstop = (): void => {
    if (callerRecorder === rec) callerRecorder = null;
    if (chunks.length) {
      let mime = rec.mimeType || mimeType || "audio/webm";
      // Never send a video container to Whisper (400 invalid format).
      if (mime.startsWith("video/")) mime = "audio/webm";
      const blob = new Blob(chunks, { type: mime });
      // Queue keeps captions in spoken order across windows.
      callerQueue = callerQueue.then(() => transcribeCallerChunk(blob));
    }
    // Chain the next window while still enabled.
    if (callerOn) startCallerWindow();
  };
  try {
    rec.start();
  } catch (e) {
    if (callerRecorder === rec) callerRecorder = null;
    addMsg("err", `Could not start caller capture: ${e instanceof Error ? e.message : String(e)}`);
    void stopCallerCapture(null);
    return;
  }
  if (callerWindowTimer !== null) window.clearTimeout(callerWindowTimer);
  callerWindowTimer = window.setTimeout(() => {
    callerWindowTimer = null;
    if (callerOn && callerRecorder === rec) {
      try {
        rec.stop();
      } catch {
        /* already stopped */
      }
    }
  }, CALLER_WINDOW_MS);
}

async function stopCallerCapture(note: string | null): Promise<void> {
  callerOn = false;
  if (callerWindowTimer !== null) {
    window.clearTimeout(callerWindowTimer);
    callerWindowTimer = null;
  }
  const rec = callerRecorder;
  callerRecorder = null;
  if (rec) {
    try {
      rec.stop(); // onstop transcribes the final window, no chaining (callerOn false)
    } catch {
      /* already stopped */
    }
  } else {
    stopCallerTracks();
    callerBusy = false;
    setCallerUI(false, "off");
  }
  if (note) addMsg("assistant", note);
  if (!rec) addMsg("assistant", "Caller voice off. Press Send to answer the last caller line.");
  else {
    // Message after the final window's caption is queued.
    callerQueue = callerQueue.then(() => {
      stopCallerTracks();
      callerBusy = false;
      setCallerUI(false, "off");
      addMsg("assistant", "Caller voice off. Press Send to answer the last caller line.");
    });
  }
}

saveBtn.addEventListener("click", saveSettings);
providerEl.addEventListener("change", loadSettings);
sendBtn.addEventListener("click", () => void send());
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") void send();
});
shotBtn.addEventListener("click", () => void captureScreenshot());
readBtn.addEventListener("click", () => void openSourcePicker());
pickerClose.addEventListener("click", () => pickerWrap.classList.add("hidden"));
listenBtn.addEventListener("click", () => void toggleListen());
callerBtn.addEventListener("click", () => void toggleCaller());
stayBtn.addEventListener("click", () => {
  stayOn = !stayOn;
  stayBtn.classList.toggle("on", stayOn);
  stayBtn.textContent = stayOn ? "Stay On: On" : "Stay On: Off";
  window.assistant?.setStayMode(stayOn);
  addMsg(
    "assistant",
    stayOn
      ? "Stay On Mode enabled — above fullscreen apps, hides after 5s idle, returns on mouse move."
      : "Stay On Mode disabled — back to normal always-on-top."
  );
});
speakBtn.addEventListener("click", () => toggleSpeak());
clearImgBtn.addEventListener("click", () => {
  attachedImage = null;
  previewWrap.classList.add("hidden");
});
hideBtn.addEventListener("click", () => window.assistant?.hide());
minBtn?.addEventListener("click", () => window.assistant?.minimize());

loadSettings();
addMsg("assistant", "Welcome. No taskbar icon, hidden from capture. Press Ctrl+Shift+A to show / hide.");
